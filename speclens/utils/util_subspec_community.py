#!/usr/bin/env python3
"""Classify indexed CommunityList values against computed subspec goals."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils import util_file, util_keyword
from utils.util_data import ConfigVariable, LineLevelConfigGroup
from utils.util_log import get_logger
from utils.util_smt import (
    parse_z3_output,
    run_z3_text,
    strip_subspec_suffixes,
    subspec_to_smt2_asserts,
)

logger = get_logger(__name__)

CommunityClassification = Tuple[List[str], List[str]]


class CommunitySubspecCalculator:
    """Classify community values that satisfy a field- or line-level goal."""

    def __init__(
        self,
        work_dir: Path,
        field_level_intermediate_dir: Path,
        line_level_intermediate_dir: Path,
        smt_source_file: Optional[Path] = None,
    ) -> None:
        self.work_dir = work_dir
        self.consistency_check_dir = (
            work_dir / util_keyword.CONSISTENCY_CHECK_DIR
        )
        self.field_level_intermediate_dir = field_level_intermediate_dir
        self.line_level_intermediate_dir = line_level_intermediate_dir
        self.smt_source_file = smt_source_file
        (
            self.community_bit_width,
            self.community_to_index,
        ) = util_file.load_community_index(work_dir)
        if self.community_bit_width <= 0 or not self.community_to_index:
            raise ValueError(
                "Community subspecification requires a non-empty BitVec index"
            )
        self._declarations_by_source: Dict[Path, Tuple[str, ...]] = {}

    def is_community_config_variable(self, config_name: str) -> bool:
        """Return whether a Config variable stores a CommunityList BitVec."""
        return "CommunityList" in config_name and config_name.endswith(
            "_community"
        )

    def classify_values(
        self,
        config_var: ConfigVariable,
        device: str,
        base_subspec: str,
        action_var: Optional[ConfigVariable] = None,
        action_value: Optional[bool] = None,
        is_line_level: bool = False,
    ) -> CommunityClassification:
        """Partition indexed communities by candidate satisfiability."""
        configurable: List[str] = []
        nonconfigurable: List[str] = []
        for community in sorted(self.community_to_index):
            target = (
                configurable
                if self._is_candidate_satisfiable(
                    config_var,
                    device,
                    base_subspec,
                    community,
                    action_var,
                    action_value,
                    is_line_level,
                )
                else nonconfigurable
            )
            target.append(community)
        return configurable, nonconfigurable

    def append_classification(
        self,
        base_subspec: str,
        configurable: List[str],
        nonconfigurable: List[str],
        action_type: Optional[str] = None,
    ) -> Optional[str]:
        """Append community classifications in the pipeline output format."""
        if base_subspec == "empty":
            return None
        qualifier = f" ({action_type})" if action_type else ""
        return " AND ".join(
            (
                base_subspec,
                f"configurable{qualifier} = {{{', '.join(configurable)}}}",
                f"nonconfigurable{qualifier} = "
                f"{{{', '.join(nonconfigurable)}}}",
            )
        )

    def find_line_variables(
        self,
        line_group: LineLevelConfigGroup,
    ) -> Tuple[Optional[ConfigVariable], Optional[ConfigVariable]]:
        """Return the CommunityList value and action variables for one line."""
        community_var = None
        action_var = None
        for config_var in line_group.config_variables:
            if self.is_community_config_variable(config_var.name):
                community_var = config_var
            elif config_var.name.endswith("_action"):
                action_var = config_var
        return community_var, action_var

    def extend_line_subspec(
        self,
        line_group: LineLevelConfigGroup,
        base_subspec: str,
    ) -> List[str]:
        """Append community classifications to one line-level subspec."""
        community_var, action_var = self.find_line_variables(line_group)
        if community_var is None:
            return [base_subspec]
        if action_var is None:
            configurable, nonconfigurable = self.classify_values(
                community_var,
                line_group.device,
                base_subspec,
                is_line_level=True,
            )
            merged = self.append_classification(
                base_subspec,
                configurable,
                nonconfigurable,
            )
            return [merged] if merged else [base_subspec]

        parts = [base_subspec]
        for action_name, action_value in (("permit", True), ("deny", False)):
            configurable, nonconfigurable = self.classify_values(
                community_var,
                line_group.device,
                base_subspec,
                action_var=action_var,
                action_value=action_value,
                is_line_level=True,
            )
            parts.extend(
                (
                    f"configurable ({action_name}) = "
                    f"{{{', '.join(configurable)}}}",
                    f"nonconfigurable ({action_name}) = "
                    f"{{{', '.join(nonconfigurable)}}}",
                )
            )
        return [" AND ".join(parts)]

    def _is_candidate_satisfiable(
        self,
        config_var: ConfigVariable,
        device: str,
        base_subspec: str,
        community: str,
        action_var: Optional[ConfigVariable],
        action_value: Optional[bool],
        is_line_level: bool,
    ) -> bool:
        query = self._candidate_query(
            config_var,
            device,
            base_subspec,
            community,
            action_var,
            action_value,
        )
        output_file = self._candidate_file(
            config_var,
            device,
            community,
            action_value,
            is_line_level,
        )
        util_file.write_text(output_file, query)
        result = run_z3_text(query)
        if result.returncode != 0 or "(error" in result.stdout:
            diagnostic = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"Z3 failed while testing community {community}: {diagnostic}"
            )
        is_sat, status = parse_z3_output(result)
        if status not in ("sat", "unsat"):
            raise RuntimeError(
                f"Unexpected Z3 result while testing community "
                f"{community}: {status}"
            )
        logger.info(
            "Community %s%s: %s",
            community,
            self._action_label(action_value),
            status,
        )
        return is_sat

    def _candidate_query(
        self,
        config_var: ConfigVariable,
        device: str,
        base_subspec: str,
        community: str,
        action_var: Optional[ConfigVariable],
        action_value: Optional[bool],
    ) -> str:
        core_subspec, _ = strip_subspec_suffixes(base_subspec)
        constraints = subspec_to_smt2_asserts(core_subspec)
        constraints.append(
            f"(= {config_var.name} {self._community_bitvec(community)})"
        )
        if action_var is not None and action_value is not None:
            action_literal = "true" if action_value else "false"
            constraints.append(f"(= {action_var.name} {action_literal})")
        lines = [
            "; CommunityList candidate subspec check",
            f"; Device: {device}",
            f"; Community: {community}",
            *self._declarations_for_device(device),
            "",
            *(f"(assert {constraint})" for constraint in constraints),
            util_keyword.SMT_CHECK_SAT,
        ]
        return "\n".join(lines) + "\n"

    def _declarations_for_device(self, device: str) -> Tuple[str, ...]:
        source_file = self.smt_source_file or (
            self.consistency_check_dir
            / util_file.violation_check_file_name(device)
        )
        cached = self._declarations_by_source.get(source_file)
        if cached is not None:
            return cached
        if not source_file.is_file():
            raise FileNotFoundError(
                f"Community subspec SMT source not found for "
                f"{device}: {source_file}"
            )
        declarations, _ = util_file.extract_synthesis_metadata(source_file)
        if not declarations:
            raise ValueError(
                f"No SMT declarations found for community subspec test: "
                f"{source_file}"
            )
        result = tuple(sorted(set(declarations)))
        self._declarations_by_source[source_file] = result
        return result

    def _candidate_file(
        self,
        config_var: ConfigVariable,
        device: str,
        community: str,
        action_value: Optional[bool],
        is_line_level: bool,
    ) -> Path:
        safe_config = util_file.safe_filename_component(config_var.name)
        safe_community = util_file.safe_filename_component(community)
        action = ""
        if action_value is not None:
            action = "_permit" if action_value else "_deny"
        output_dir = (
            self.line_level_intermediate_dir
            if is_line_level
            else self.field_level_intermediate_dir
        )
        return output_dir / (
            f"community_candidate_{device}_{safe_config}"
            f"{action}_{safe_community}.smt2"
        )

    def _community_bitvec(self, community: str) -> str:
        try:
            index = self.community_to_index[community]
        except KeyError as error:
            raise ValueError(f"Unknown indexed community: {community}") from error
        return f"#b{1 << index:0{self.community_bit_width}b}"

    @staticmethod
    def _action_label(action_value: Optional[bool]) -> str:
        if action_value is True:
            return " permit"
        if action_value is False:
            return " deny"
        return ""
