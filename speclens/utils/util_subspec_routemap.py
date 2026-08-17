"""Compute route-map subspecifications from satisfaction-check models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from utils import util_file, util_keyword
from utils.util_log import get_logger
from utils.util_smt import (
    append_check_sat,
    append_get_model,
    parse_z3_model_assignments,
    parse_z3_output,
    prefix_string_to_constraint,
    require_successful_z3_output,
    run_z3_text,
)

logger = get_logger(__name__)


_ROUTEMAP_ATTRIBUTE_PATTERNS = (
    re.compile(r"_community_\^[^_]+_\w+$"),
    re.compile(r"_community_[^_]+$"),
    re.compile(r"_permitted$"),
    re.compile(r"_prefixLength$"),
    re.compile(r"_metric$"),
    re.compile(r"_med$"),
    re.compile(r"_choice$"),
)
_ROUTEMAP_ATTRIBUTE_TOKENS = (
    "_permitted",
    "_prefixLength",
    "_metric",
    "_med",
    "_choice",
    "_community_",
)
_COMMUNITY_VALUE_RE = re.compile(r"community_([0-9]+:[0-9]+)")


class RoutemapSubspecCalculator:
    """Calculate route-map-level subspecs for selected devices."""

    def __init__(
        self,
        work_dir: Path,
        devices: List[str],
        test_output_dir: Path,
        device_filter: Optional[str] = None,
    ) -> None:
        self.work_dir = work_dir
        self.devices = devices
        self.test_output_dir = test_output_dir
        self.device_filter = device_filter
        self.subspec_files_dir = work_dir / util_keyword.ROUTEMAP_SUBSPEC_DIR
        util_file.ensure_directory(self.subspec_files_dir)

    @staticmethod
    def _extract_routemap_prefix(var_name: str) -> Optional[str]:
        if not (var_name.startswith("|0_") and var_name.endswith("|")):
            return None

        inner = var_name[3:-1]
        if "_BGP_" not in inner:
            return None
        if "__" in inner:
            separator = inner.find("__")
            if separator > 0:
                return f"|0_{inner[:separator]}"

        direction_end = RoutemapSubspecCalculator._bgp_direction_end(inner)
        if direction_end is None:
            return None
        for pattern in _ROUTEMAP_ATTRIBUTE_PATTERNS:
            match = pattern.search(inner)
            if match:
                return f"|0_{inner[:match.start()]}"
        for token in _ROUTEMAP_ATTRIBUTE_TOKENS:
            position = inner.find(token, direction_end)
            if position >= direction_end:
                return f"|0_{inner[:position]}"
        return None

    @staticmethod
    def _bgp_direction_end(var_name: str) -> Optional[int]:
        for token in ("_BGP_IMPORT_", "_BGP_EXPORT_"):
            position = var_name.find(token)
            if position >= 0:
                return position + len(token)
        return None

    @staticmethod
    def _parse_z3_model(model_output: str) -> Dict[str, str]:
        return parse_z3_model_assignments(model_output)

    @staticmethod
    def _sort_routemap_variables(variables: List[str]) -> List[str]:
        groups: List[List[str]] = [[] for _ in range(9)]
        for variable in variables:
            if variable.endswith("_choice|"):
                index = 0
            elif variable.endswith("_permitted|"):
                index = 1
            elif variable.endswith("_prefixLength|"):
                index = 2
            elif variable.endswith("_metric|"):
                index = 3
            elif variable.endswith("_med|"):
                index = 4
            elif "_community_" not in variable:
                index = 5
            elif "_community_^" in variable and variable.endswith("_OTHER|"):
                index = 7
            elif "_community_^" in variable and variable.endswith("_REGEX|"):
                index = 8
            else:
                index = 6
            groups[index].append(variable)

        return [
            variable
            for group in groups
            for variable in sorted(group)
        ]

    @staticmethod
    def _format_routemap_name(routemap_prefix: str) -> str:
        name = routemap_prefix.removeprefix("|")
        return re.sub(r"(\d+)/(\d+)", r"\1_\2", name)

    def _load_prefix_constraints(self) -> Optional[str]:
        destination_file = self.work_dir / util_keyword.DST_IPS_FILE
        if not destination_file.is_file():
            raise FileNotFoundError(
                f"Destination IP file not found: {destination_file}"
            )

        constraints = [
            constraint
            for prefix in util_file.load_data_lines(destination_file)
            if (constraint := prefix_string_to_constraint(prefix))
        ]
        return " AND ".join(constraints) or None

    def _build_subspec_from_model(
        self,
        routemap_prefix: str,
        model: Dict[str, str],
        prefix_constraints: Optional[str] = None,
    ) -> str:
        variables = [
            variable for variable in model if variable.startswith(routemap_prefix)
        ]
        if not variables:
            return ""

        choice_variables = [
            variable for variable in variables if variable.endswith("_choice|")
        ]
        if choice_variables and len(choice_variables) == len(variables):
            return "non route-map"

        permitted_variables = [
            variable for variable in variables if variable.endswith("_permitted|")
        ]
        if (
            permitted_variables
            and model[permitted_variables[0]].strip().lower() == "false"
        ):
            return "empty"

        constraints = [prefix_constraints] if prefix_constraints else []
        value_variables = [
            variable
            for variable in variables
            if not variable.endswith(("_permitted|", "_choice|"))
            and "_community_" not in variable
        ]
        constraints.extend(
            f"(= {variable} {model[variable]})"
            for variable in self._sort_routemap_variables(value_variables)
        )
        return " AND ".join(constraints)

    def _get_all_possible_communities(self) -> Set[str]:
        index_file = self.work_dir / util_keyword.COMMUNITY_INDEXES_FILE
        if not index_file.is_file():
            return set()
        _, communities = util_file.load_community_index(self.work_dir)
        return {community for community in communities if ":" in community}

    @staticmethod
    def _extract_community_variables_for_routemap(
        routemap_prefix: str,
        model: Dict[str, str],
    ) -> List[str]:
        return sorted(
            variable
            for variable in model
            if variable.startswith(routemap_prefix)
            and "_community_" in variable
            and "_OTHER" not in variable
            and "_REGEX" not in variable
        )

    @staticmethod
    def _community_constraints(
        community_variables: Sequence[str],
        test_community: Optional[str],
    ) -> List[str]:
        constraints: List[str] = []
        for variable in community_variables:
            match = _COMMUNITY_VALUE_RE.search(variable)
            if test_community is None:
                value = "false"
            elif match:
                value = "true" if match.group(1) == test_community else "false"
            else:
                continue
            constraints.append(f"(assert (= {variable} {value}))")
        return constraints

    def _test_community_configurable(
        self,
        device: str,
        routemap_prefix: str,
        community_vars: List[str],
        test_community: Optional[str],
        forward_file_path: Path,
    ) -> bool:
        content = util_file.load_text(forward_file_path)
        check_sat_position = content.find(util_keyword.SMT_CHECK_SAT)
        if check_sat_position < 0:
            raise ValueError(
                f"Missing {util_keyword.SMT_CHECK_SAT} in {forward_file_path}"
            )

        label = test_community if test_community is not None else "none"
        constraints = self._community_constraints(
            community_vars, test_community
        )
        inserted = "\n".join(
            [f"; case: community = {label}", *constraints, ""]
        )
        query = (
            content[:check_sat_position]
            + "\n"
            + inserted
            + content[check_sat_position:]
        )
        try:
            result = run_z3_text(query)
            require_successful_z3_output(
                result,
                f"route-map community {label} for {routemap_prefix} on {device}",
            )
            is_sat, status = parse_z3_output(result)
        except Exception as exc:
            raise RuntimeError(
                f"Failed route-map community check for {routemap_prefix} "
                f"on {device}, value {label}: {exc}"
            ) from exc
        if status not in {"sat", "unsat"}:
            raise RuntimeError(
                f"Unexpected Z3 result for {routemap_prefix} on {device}, "
                f"value {label}: {status}"
            )
        return is_sat

    def _calculate_routemap_community_subspecs(
        self,
        device: str,
        routemap_prefix: str,
        base_subspec: str,
        model: Dict[str, str],
        forward_file_path: Path,
    ) -> str:
        if base_subspec in {"non route-map", "empty"}:
            return base_subspec

        community_variables = self._extract_community_variables_for_routemap(
            routemap_prefix, model
        )
        if not community_variables or not self._get_all_possible_communities():
            return base_subspec

        available = {
            match.group(1)
            for variable in community_variables
            if (match := _COMMUNITY_VALUE_RE.search(variable))
        }
        configurable = [
            community
            for community in sorted(available)
            if self._test_community_configurable(
                device,
                routemap_prefix,
                community_variables,
                community,
                forward_file_path,
            )
        ]
        if self._test_community_configurable(
            device,
            routemap_prefix,
            community_variables,
            None,
            forward_file_path,
        ):
            configurable.append("none")

        if not configurable:
            return base_subspec
        values = ", ".join(configurable)
        return f"{base_subspec} AND configurable = {{{values}}}"

    def _devices_to_process(self) -> List[str]:
        if self.device_filter is None:
            return list(self.devices)
        if self.device_filter not in self.devices:
            raise ValueError(
                f"Device '{self.device_filter}' not found; available devices: "
                f"{', '.join(self.devices)}"
            )
        return [self.device_filter]

    def _load_device_model(self, device: str) -> tuple[Path, Dict[str, str]]:
        satisfaction_file = (
            self.test_output_dir
            / util_file.satisfaction_check_file_name(device)
        )
        if not satisfaction_file.is_file():
            raise FileNotFoundError(
                f"Satisfaction check not found for {device}: {satisfaction_file}"
            )

        query = append_get_model(
            append_check_sat(util_file.load_text(satisfaction_file))
        )
        try:
            result = run_z3_text(query)
            output = require_successful_z3_output(
                result, f"route-map model for {device}"
            )
            is_sat, status = parse_z3_output(result)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to obtain route-map model for {device} from "
                f"{satisfaction_file}: {exc}"
            ) from exc
        if not is_sat:
            raise RuntimeError(
                f"Expected SAT route-map model for {device}, got {status}"
            )
        return satisfaction_file, self._parse_z3_model(output)

    def _calculate_device_subspecs(
        self,
        device: str,
        prefix_constraints: Optional[str],
    ) -> Dict[str, Set[str]]:
        satisfaction_file, model = self._load_device_model(device)
        prefixes = sorted(
            {
                prefix
                for variable in model
                if "_BGP_" in variable
                if (prefix := self._extract_routemap_prefix(variable))
            }
        )
        subspecs: Dict[str, Set[str]] = {}
        for prefix in prefixes:
            subspec = self._build_subspec_from_model(
                prefix, model, prefix_constraints
            )
            if not subspec:
                continue
            if subspec not in {"non route-map", "empty"}:
                subspec = self._calculate_routemap_community_subspecs(
                    device,
                    prefix,
                    subspec,
                    model,
                    satisfaction_file,
                )
            subspecs.setdefault(prefix, set()).add(subspec)
        return subspecs

    @staticmethod
    def _merge_subspecs(
        destination: Dict[str, Set[str]],
        source: Dict[str, Set[str]],
    ) -> None:
        for prefix, subspecs in source.items():
            destination.setdefault(prefix, set()).update(subspecs)

    def _output_file(self) -> Path:
        output_name = util_keyword.ROUTEMAP_SUBSPECS_FILE
        if self.device_filter:
            stem = output_name.removesuffix(".txt")
            output_name = f"{stem}_{self.device_filter}.txt"
        return self.subspec_files_dir / output_name

    def _render_subspecs(self, subspecs: Dict[str, Set[str]]) -> str:
        lines = ["Route-Map Level Subspecs", "========================", ""]
        if not subspecs:
            lines.append("No route-map level subspecs found.")
            return "\n".join(lines) + "\n"

        for prefix in sorted(subspecs):
            values = sorted(subspecs[prefix])
            lines.append(f"RouteMap: {self._format_routemap_name(prefix)}")
            if values:
                lines.append(f"Subspecs ({len(values)}):")
                lines.extend(
                    f"  {index}. {subspec}"
                    for index, subspec in enumerate(values, 1)
                )
            else:
                lines.append("No subspecs found.")
            lines.extend(["-" * 50, ""])
        return "\n".join(lines) + "\n"

    def calculate_routemap_subspecs(self) -> None:
        """Calculate and save route-map subspecifications."""
        prefix_constraints = self._load_prefix_constraints()
        subspecs: Dict[str, Set[str]] = {}
        for device in self._devices_to_process():
            self._merge_subspecs(
                subspecs,
                self._calculate_device_subspecs(
                    device, prefix_constraints
                ),
            )

        output_file = self._output_file()
        util_file.write_text(output_file, self._render_subspecs(subspecs))
        logger.info("Route-map level subspecs saved to: %s", output_file)
