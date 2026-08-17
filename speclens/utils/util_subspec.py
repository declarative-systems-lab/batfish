"""Provide shared subspec simplification and impact-check operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Set, Tuple

from utils import util_file
from utils import util_keyword
from utils.util_data import ConfigVariable, ConfigVariablePair, LineLevelConfigGroup
from utils.util_log import get_logger, verbose_debug, verbose_info
from utils.util_norm import normalize_subspec
from utils.util_subspec_community import CommunitySubspecCalculator
from utils.util_smt import (
    append_check_sat,
    get_bounds_for_multiple_config_variables,
    get_bounds_for_single_config_variable,
    extract_base_name_for_ip_mask,
    extract_config_constraints_from_z3_goal,
    get_device_for_config_var,
    get_mask_variable_names_from_pairs,
    is_ip_mask_pair,
    parse_z3_output,
    replace_check_sat_with_simplify,
    require_successful_z3_output,
    run_z3_file,
    strip_subspec_suffixes,
    subspec_string_to_list,
)

logger = get_logger(__name__)


class SubspecResult(Protocol):
    """Result fields required by the shared completion formatters."""

    config_variable_pairs: Sequence[ConfigVariablePair]
    device_filter: Optional[str]
    field_level_only: bool
    line_level_only: bool
    line_level_subspecs: Dict[str, Set[str]]
    subspecs: Dict[str, Set[str]]


class NamedValue(Protocol):
    """Minimal configuration-variable interface used by impact checks."""

    name: str
    value: str


_LINE_PREFIX_PATTERNS = (
    re.compile(r"(Config_\S+__Line\d+__[Ll]ine\d+)"),
    re.compile(r"(Config_\S+__Line\d+)"),
)


def _mask_variable_names(
    pairs: Sequence[ConfigVariablePair],
) -> Set[str]:
    return get_mask_variable_names_from_pairs(
        [(pair.ip_var.name, pair.mask_var.name) for pair in pairs]
    )


def _visible_field_subspecs(
    result: SubspecResult,
) -> Dict[str, Set[str]]:
    mask_names = _mask_variable_names(result.config_variable_pairs)
    return {
        name: values
        for name, values in result.subspecs.items()
        if name not in mask_names
    }


def _count_nonempty(
    subspecs: Dict[str, Set[str]],
) -> Tuple[int, int]:
    nonempty = sum(
        bool(values and values != {"empty"}) for values in subspecs.values()
    )
    return nonempty, len(subspecs)


def _percentage(nonempty: int, total: int) -> str:
    value = 100.0 * nonempty / total if total else 0.0
    return f"{value:.1f}%"


def build_ip_mask_pairs(
    config_variables: Sequence[ConfigVariable],
) -> List[ConfigVariablePair]:
    """Build unique IP/mask pairs while preserving discovery order."""
    logger.info("Extracting ip/mask pairs from config variables...")
    base_name_to_vars: Dict[str, Dict[str, ConfigVariable]] = {}

    for config_var in config_variables:
        base_name = extract_base_name_for_ip_mask(config_var.name)
        if base_name == config_var.name:
            continue
        base_name_to_vars.setdefault(base_name, {}).setdefault(
            config_var.name, config_var
        )

    pairs: List[ConfigVariablePair] = []
    for base_name, variables_by_name in base_name_to_vars.items():
        variables = list(variables_by_name.values())
        if len(variables) == 2:
            first, second = variables
            if is_ip_mask_pair(first.name, second.name):
                ip_var, mask_var = (
                    (first, second) if first.name.endswith("__ip") else (second, first)
                )
                pairs.append(
                    ConfigVariablePair(
                        ip_var=ip_var,
                        mask_var=mask_var,
                        base_name=base_name,
                    )
                )
                logger.info("Found ip/mask pair: %s + %s", ip_var.name, mask_var.name)
            else:
                logger.warning(
                    "Two variables with same base name but not ip/mask pair: %s, %s",
                    first.name,
                    second.name,
                )
        elif len(variables) > 2:
            logger.warning("More than 2 variables with same base name: %s", base_name)
            logger.warning("Variables: %s", [var.name for var in variables])
        elif variables:
            logger.info(
                "Only one variable found for base name %s: %s",
                base_name,
                variables[0].name,
            )

    logger.info("Found %d ip/mask pairs", len(pairs))
    return pairs


def print_subspec_result_counts(calculator: SubspecResult) -> None:
    """Print the common field/line totals emitted by simplifier entry points."""
    if not calculator.line_level_only:
        field_subspecs = _visible_field_subspecs(calculator)
        empty_count = sum(
            1 for values in field_subspecs.values() if not values or values == {"empty"}
        )
        print(
            f"field-level: {len(field_subspecs)} config field, "
            f"{empty_count} empty subspec"
        )
    if not calculator.field_level_only:
        empty_count = sum(
            1
            for values in calculator.line_level_subspecs.values()
            if not values or values == {"empty"}
        )
        print(
            f"line-level: {len(calculator.line_level_subspecs)} config line, "
            f"{empty_count} empty subspec"
        )


def print_subspec_completion(device_filter: Optional[str]) -> None:
    """Print the compact non-verbose completion message."""
    if device_filter:
        print(f"Device {device_filter}: ✓ Completed")
    else:
        print("All devices: ✓ Completed")


def format_subspec_completion(calculator: SubspecResult, label: str) -> str:
    """Build a one-line field/line subspecification coverage summary."""
    level_summaries = []
    overall_nonempty = 0
    overall_total = 0

    if not calculator.field_level_only:
        line_nonempty, line_total = _count_nonempty(
            calculator.line_level_subspecs
        )
        overall_nonempty += line_nonempty
        overall_total += line_total
        level_summaries.append(
            f"Line-Level Subspec {_percentage(line_nonempty, line_total)}"
        )

    if not calculator.line_level_only:
        field_nonempty, field_total = _count_nonempty(
            _visible_field_subspecs(calculator)
        )
        overall_nonempty += field_nonempty
        overall_total += field_total
        level_summaries.append(
            f"Field-Level Subspec {_percentage(field_nonempty, field_total)}"
        )

    device = (
        f" for device {calculator.device_filter}"
        if calculator.device_filter
        else ""
    )
    overall = _percentage(overall_nonempty, overall_total)
    return (
        f"[✓] Completed: #{label} {overall}{device} "
        f"({', '.join(level_summaries)})"
    )


class CommonSubspecSimplifierMixin:
    """Shared field/pair/line helpers for subspec stages 4 through 8.

    Concrete workflows provide their baseline-specific ``_write_compute_*`` and
    ``_parse_*`` methods plus the attributes referenced here.
    """

    subspec_stage: int
    persistent_metadata: bool = False
    initialize_unmatched_communities: bool = False

    def _verbose_info(self, message: str, *args) -> None:
        """Emit an INFO message using this workflow's verbose flag."""
        verbose_info(self.verbose, message, *args)

    def _init_output_dirs(self) -> None:
        """Initialize the stage's standard output and intermediate directories."""
        layout = util_file.initialize_subspec_directories(
            self.work_dir,
            stage=self.subspec_stage,
            verbose=self.verbose,
            persistent_metadata=self.persistent_metadata,
        )
        self.temp_dir_obj = layout.temporary_directory
        self.subspec_files_dir = layout.output_dir
        self.subspec_baseline_files_dir = layout.metadata_dir
        self.field_level_intermediate_dir = layout.field_intermediate_dir
        self.line_level_intermediate_dir = layout.line_intermediate_dir
        if self.initialize_unmatched_communities:
            self.unmatched_community_var_names = (
                self._load_unmatched_community_names()
            )

    def _load_unmatched_community_names(self) -> Set[str]:
        unmatched_file = self.work_dir / util_keyword.EMPTY_COMMUNITIES_FILE
        if not unmatched_file.is_file():
            logger.debug(
                "%s not found; no unmatched-community empty shortcut",
                util_keyword.EMPTY_COMMUNITIES_FILE,
            )
            return set()

        names = set(util_file.load_data_lines(unmatched_file))
        logger.info(
            "Loaded %d unmatched community var names from %s",
            len(names),
            util_keyword.EMPTY_COMMUNITIES_FILE,
        )
        return names

    def extract_ip_mask_pairs(self) -> None:
        """Populate IP/mask pairs from the workflow's Config variables."""
        self.config_variable_pairs = build_ip_mask_pairs(self.config_variables)

    def _prepare_metadata_file(
        self, config_var: ConfigVariable, device: str
    ) -> Optional[Path]:
        return util_file.prepare_config_synthesis_metadata(
            config_var.name,
            device,
            compute_dir=self.field_level_intermediate_dir,
            metadata_dir=self.subspec_baseline_files_dir,
            metadata_type="field",
        )

    def _normalize_subspec_with_metadata(
        self,
        subspec: str,
        config_var: ConfigVariable,
        metadata_file: Optional[Path],
    ) -> str:
        """Normalize one field-level simplification goal."""
        return self._normalize_simplification_goal(
            subspec,
            metadata_file=metadata_file,
            config_name=config_var.name,
            is_field_level=True,
            is_pair=False,
            intermediate_dir=self.field_level_intermediate_dir,
        )

    def _normalize_simplification_goal(
        self,
        goal: str,
        *,
        metadata_file: Optional[Path],
        config_name: str,
        is_field_level: bool,
        is_pair: bool,
        intermediate_dir: Path,
        config_names: Optional[Set[str]] = None,
    ) -> str:
        """Normalize one parsed Z3 goal, preserving suffixes and safe fallback."""
        if not metadata_file:
            verbose_debug(
                self.verbose,
                f"  Metadata file not found for {config_name}, skipping normalization",
            )
            return goal

        try:
            core, suffix = strip_subspec_suffixes(goal)
            normalized = normalize_subspec(
                core,
                metadata_file,
                config_name,
                is_field_level=is_field_level,
                is_pair=is_pair,
                target_dst_ip=self.target_dst_ip,
                max_iterations=util_keyword.SUBSPEC_NORM_COUNT,
                verbose=self.verbose,
                temp_dir=intermediate_dir,
                config_names=config_names,
            )
            result = normalized + suffix
            verbose_info(self.verbose, f"  Normalized subspec: {result}")
            return result
        except Exception as exc:
            raise RuntimeError(
                f"Failed to normalize subspec for {config_name}: {exc}"
            ) from exc

    def _normalize_pair_subspec_with_metadata(
        self,
        config_pair: ConfigVariablePair,
        subspec: str,
        device: Optional[str],
    ) -> str:
        """Normalize one IP/mask-pair subspec when its metadata is available."""
        if not device:
            raise ValueError(
                f"Could not determine device for config pair "
                f"{config_pair.base_name}"
            )

        metadata_file = util_file.prepare_config_synthesis_metadata(
            config_pair.base_name,
            device,
            compute_dir=self.field_level_intermediate_dir,
            metadata_dir=self.subspec_baseline_files_dir,
            metadata_type="pair",
        )
        if not metadata_file:
            verbose_debug(
                self.verbose,
                f"  Metadata file not found for {config_pair.base_name}, "
                "skipping normalization",
            )
            return subspec

        return self._normalize_simplification_goal(
            subspec,
            metadata_file=metadata_file,
            config_name=config_pair.base_name,
            is_field_level=True,
            is_pair=True,
            intermediate_dir=self.field_level_intermediate_dir,
        )

    def _merge_pair_subspecs_into_field(
        self, config_pair: ConfigVariablePair
    ) -> None:
        """Merge a pair result into the IP variable's field-level results."""
        pair_subspecs = self.pair_subspecs[config_pair.base_name]
        ip_var_name = config_pair.ip_var.name
        self.subspecs.setdefault(ip_var_name, set()).update(pair_subspecs)

        if not pair_subspecs:
            logger.info("  No subspecs found for %s", config_pair.base_name)
            return

        logger.info(
            "  Final subspecs for %s: %s",
            config_pair.base_name,
            list(pair_subspecs),
        )
        logger.info(
            "  Added to IP variable %s field-level subspecs", ip_var_name
        )

    def _cleanup_pair_subspec_files(
        self,
        config_pair: ConfigVariablePair,
        device: Optional[str],
    ) -> None:
        """Remove one pair's temporary SMT and metadata files when appropriate."""
        if not device:
            return
        safe_base_name = util_file.safe_filename_component(config_pair.base_name)
        self._delete_intermediate_files_for_target(
            self.field_level_intermediate_dir,
            device,
            safe_base_name,
        )
        self._delete_metadata_file_for_target("pair", device, safe_base_name)

    @staticmethod
    def _comment_config_var_equality_and_add_bounds(
        lines: List[str], config_var: ConfigVariable
    ) -> Tuple[List[str], bool]:
        return comment_config_var_equality_and_add_bounds(lines, config_var)

    @staticmethod
    def _comment_out_line_group(
        file_path: str, line_group, comment: bool = True
    ) -> str:
        return comment_existing_config_equalities_to_temp(
            Path(file_path), line_group.config_variables, comment=comment
        )

    @staticmethod
    def _comment_out_config_pair(
        file_path: str, config_pair, comment: bool = True
    ) -> str:
        return comment_existing_config_equalities_to_temp(
            Path(file_path),
            [config_pair.ip_var, config_pair.mask_var],
            comment=comment,
        )

    def _delete_intermediate_files_for_target(
        self,
        intermediate_dir: Path,
        device: str,
        safe_name: str,
        extra_safe_names: Optional[List[str]] = None,
    ) -> None:
        if self.verbose:
            return
        util_file.delete_subspec_target_intermediates(
            intermediate_dir,
            device,
            safe_name,
            extra_safe_names=extra_safe_names,
        )

    def _delete_metadata_file_for_target(
        self, metadata_type: str, device: str, safe_name: str
    ) -> None:
        if (
            self.verbose
            or metadata_type == "line"
            or not device
            or not self.subspec_baseline_files_dir
        ):
            return
        util_file.delete_subspec_metadata_files(
            self.subspec_baseline_files_dir,
            metadata_type,
            device,
            safe_name,
        )

    def _run_z3_simplify_and_parse(
        self,
        smt2_path: Path,
        log_label: str,
        parse_fn: Callable[[str], Optional[str]],
        cleanup_after: bool = False,
    ) -> Optional[str]:
        try:
            try:
                result = run_z3_file(smt2_path)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to run Z3 simplification for {log_label}: {exc}"
                ) from exc

            output = require_successful_z3_output(
                result, f"simplification {log_label}"
            )

            logger.info("    Z3 Simplification Results for %s:", log_label)
            logger.info("    " + "=" * 60)
            for line in output.split("\n"):
                logger.info("    %s", line)
            logger.info("    " + "=" * 60)
            try:
                return parse_fn(output)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to parse Z3 simplification for {log_label}: {exc}"
                ) from exc
        finally:
            if cleanup_after and smt2_path:
                util_file.delete_file(smt2_path)

    def _compute_subspec_field_level(
        self, config_var: ConfigVariable, device: str
    ) -> Optional[str]:
        smt2_path = self._write_compute_smt2_field_level(config_var, device)
        if not smt2_path:
            return None
        return self._run_z3_simplify_and_parse(
            smt2_path,
            f"{config_var.name} on {device}",
            lambda output: self._parse_simplification_output(output, config_var),
            # The caller still needs this SMT file to extract synthesis
            # metadata and normalize the parsed subspec.  It owns cleanup
            # after those steps have completed.
            cleanup_after=False,
        )

    def _compute_subspec_line_level(self, line_group) -> Optional[str]:
        smt2_path = self._write_compute_smt2_line_level(line_group)
        if not smt2_path:
            return None
        return self._run_z3_simplify_and_parse(
            smt2_path,
            f"line group {line_group.device} - {line_group.line_id}",
            lambda output: self._parse_line_group_simplification_output(
                output, line_group
            ),
            cleanup_after=False,
        )

    def _compute_subspec_field_level_pair(self, config_pair) -> Optional[str]:
        smt2_path = self._write_compute_smt2_field_level_pair(config_pair)
        if not smt2_path:
            return None
        return self._run_z3_simplify_and_parse(
            smt2_path,
            f"config pair {config_pair.base_name}",
            lambda output: self._parse_config_pair_simplification_output(
                output, config_pair
            ),
            cleanup_after=False,
        )

    @staticmethod
    def _extract_line_prefix_from_config_name(config_name: str) -> Optional[str]:
        """Extract the outer/nested line prefix used by subspec statistics."""
        return CommonSubspecSimplifierMixin._find_line_prefix(config_name)

    @staticmethod
    def _get_line_prefix_from_config_name(config_name: str) -> Optional[str]:
        """Return a ``__LineN`` or ``__LineN__lineM`` grouping prefix."""
        return CommonSubspecSimplifierMixin._find_line_prefix(config_name)

    @staticmethod
    def _find_line_prefix(config_name: str) -> Optional[str]:
        for pattern in _LINE_PREFIX_PATTERNS:
            match = pattern.search(config_name)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _line_id_from_prefix(line_prefix: str) -> str:
        """Return the compact LineN identifier represented by a prefix."""
        nested_match = re.search(
            r"__Line(\d+)__[Ll]ine(\d+)$", line_prefix
        )
        if nested_match:
            return (
                f"Line{nested_match.group(1)}__line{nested_match.group(2)}"
            )
        line_match = re.search(r"__Line(\d+)$", line_prefix)
        return f"Line{line_match.group(1)}" if line_match else line_prefix

    def _emit_subspec_compute_summary(self) -> None:
        """Print one compact computed/total summary at the end of a run."""
        if not self.subspec_compute_summary:
            return

        field_stats = self.subspec_compute_summary.get("field")
        pair_stats = self.subspec_compute_summary.get("pair")
        if field_stats and pair_stats:
            merged_field_stats = {
                key: field_stats[key] + pair_stats[key]
                for key in (
                    "total",
                    "compute",
                    "skipped",
                    "rfl_total",
                    "rfl_compute",
                    "other_total",
                    "other_compute",
                )
            }
        else:
            merged_field_stats = field_stats or pair_stats

        def format_stats(stats: Dict[str, int], label: str) -> str:
            return (
                f"{label}: {stats['compute']}/{stats['total']} "
                f"(skipped {stats['skipped']}) | RouteFilterList "
                f"{stats['rfl_compute']}/{stats['rfl_total']}, Other "
                f"{stats['other_compute']}/{stats['other_total']}"
            )

        lines = ["Subspec computation summary (computed/total):"]
        if merged_field_stats:
            lines.append(
                f"  - {format_stats(merged_field_stats, 'Field-level subspecs')}"
            )
        line_stats = self.subspec_compute_summary.get("line")
        if line_stats:
            lines.append(
                f"  - {format_stats(line_stats, 'Line-level subspecs')}"
            )
        for line in lines:
            print(line)


class LocalAgSubspecSimplifierMixin(CommonSubspecSimplifierMixin):
    """Shared complete-forward/reverse behavior used by scripts 4 and 5."""

    initialize_unmatched_communities = True

    def _validate_input_files(self) -> None:
        try:
            util_file.validate_local_subspec_inputs(self.work_dir)
        except FileNotFoundError as exc:
            logger.error(str(exc))
            logger.error("Work directory: %s", self.work_dir)
            logger.error(
                "Hint: run `python3 2_router_local_encoding.py <work_dir>` after "
                "`1_router_level_subspec.py` to generate satisfaction/violation "
                "fragments."
            )
            raise SystemExit(1) from exc
        logger.info("All required input files/directories found")

    def _get_community_calculator(self) -> Optional[CommunitySubspecCalculator]:
        """Lazily construct the optional CommunityList calculator."""
        if not self.enable_community:
            return None
        if self.community_calculator is None:
            self.community_calculator = CommunitySubspecCalculator(
                work_dir=self.work_dir,
                field_level_intermediate_dir=self.field_level_intermediate_dir,
                line_level_intermediate_dir=self.line_level_intermediate_dir,
            )
        return self.community_calculator

    def _is_unmatched_community_var(self, config_name: str) -> bool:
        return config_name in self.unmatched_community_var_names and (
            "_set_community_" in config_name or "_add_community_" in config_name
        )

    def _get_ip_mask_variable_names(self) -> Set[str]:
        return {
            name
            for pair in self.config_variable_pairs
            for name in (pair.ip_var.name, pair.mask_var.name)
        }

    def _calculate_field_level_statistics(
        self, ip_mask_variable_names: Set[str]
    ) -> None:
        rfl_total = rfl_compute = other_total = other_compute = 0
        for config_name in self.config_vars_by_name:
            if config_name in ip_mask_variable_names:
                continue
            if self._extract_line_prefix_from_config_name(config_name):
                rfl_total += 1
                rfl_compute += int(config_name in self.config_vars_by_name)
            else:
                other_total += 1
                other_compute += int(config_name in self.config_vars_by_name)
        self.subspec_compute_summary["field"] = {
            "total": rfl_total + other_total,
            "compute": rfl_compute + other_compute,
            "skipped": 0,
            "rfl_total": rfl_total,
            "rfl_compute": rfl_compute,
            "other_total": other_total,
            "other_compute": other_compute,
        }

    def _process_community_extended_analysis(
        self,
        config_var: ConfigVariable,
        device: str,
        normalized_subspec: str,
        metadata_file: Optional[Path],
    ) -> Optional[str]:
        calculator = self._get_community_calculator()
        if not (
            calculator
            and calculator.is_community_config_variable(config_var.name)
        ):
            logger.debug(
                "  %s is not a community configuration variable",
                config_var.name,
            )
            return None
        logger.info(
            "  Detected community configuration variable (%s), performing "
            "extended analysis...",
            config_var.name,
        )
        extended_info = calculator.classify_values(
            config_var, device, normalized_subspec
        )
        if not extended_info:
            logger.warning("  Extended analysis returned None for %s", config_var.name)
            return None
        configurable, nonconfigurable = extended_info
        merged_subspec = calculator.append_classification(
            normalized_subspec, configurable, nonconfigurable
        )
        if not merged_subspec:
            logger.warning("  Failed to merge subspec for %s", config_var.name)
            return None
        final_subspec = self._normalize_subspec_with_metadata(
            merged_subspec, config_var, metadata_file
        )
        logger.info("  Merged normalized subspec: %s", final_subspec)
        return final_subspec

    def _calculate_subspec_for_config_var(
        self, config_var: ConfigVariable, device: str, _config_name: str
    ) -> Optional[str]:
        if not self._check_subspec_field_level(config_var, device):
            logger.info("  Empty subspec (no impact on combined constraint negated)")
            return "empty"
        subspec = self._compute_subspec_field_level(config_var, device)
        if not subspec:
            logger.info("  No subspec found (unique value)")
            return None
        metadata_file = self._prepare_metadata_file(config_var, device)
        normalized_subspec = self._normalize_subspec_with_metadata(
            subspec, config_var, metadata_file
        )
        logger.info("  Subspec: %s", normalized_subspec)
        final_subspec = self._process_community_extended_analysis(
            config_var, device, normalized_subspec, metadata_file
        )
        return final_subspec if final_subspec is not None else normalized_subspec

    def save_results(self) -> None:
        """Persist the standard field- and line-level subspec reports."""
        if self.field_level_only:
            logger.info("Saving field-level subspecs...")
        elif self.line_level_only:
            logger.info("Saving line-level subspecs...")
        else:
            logger.info("Saving field-level and line-level subspecs...")

        if not self.line_level_only:
            field_output_file = util_file.get_subspec_output_file_path(
                self.subspec_files_dir, "field", self.device_filter
            )
            mask_names = get_mask_variable_names_from_pairs(
                [
                    (pair.ip_var.name, pair.mask_var.name)
                    for pair in self.config_variable_pairs
                ]
            )
            util_file.save_field_level_subspecs(
                field_output_file,
                self.subspecs,
                exclude_config_names=mask_names,
            )
            logger.info("Field-level results saved to: %s", field_output_file)

        if not self.field_level_only:
            line_output_file = util_file.get_subspec_output_file_path(
                self.subspec_files_dir, "line", self.device_filter
            )
            util_file.save_line_level_subspecs(
                line_output_file, self.line_level_subspecs
            )
            logger.info("Line-level results saved to: %s", line_output_file)

        logger.info(
            "Field-level intermediate files saved to: %s",
            self.field_level_intermediate_dir,
        )
        logger.info(
            "Line-level intermediate files saved to: %s",
            self.line_level_intermediate_dir,
        )

    def load_device_info(self) -> None:
        """Load and optionally filter the canonical hostname list."""
        devices = util_file.load_hostnames(self.work_dir)
        if self.device_filter:
            if self.device_filter not in devices:
                raise ValueError(
                    f"Device '{self.device_filter}' not found in 0_hostnames.txt\n"
                    f"Available devices: {', '.join(devices)}"
                )
            devices = [self.device_filter]
            logger.info("Filtered to device: %s", devices[0])
        self.devices = devices

    def _devices_with_violation_check(self) -> List[str]:
        return sorted(
            device
            for device in self.devices
            if self._violation_check_path(device).is_file()
        )

    def _devices_with_sliced(self) -> List[str]:
        sliced_dir = self.work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
        return sorted(
            device
            for device in self.devices
            if (
                sliced_dir
                / util_file.router_local_encoding_file_name(device)
            ).is_file()
        )

    def extract_config_variables(self) -> None:
        """Extract Config equalities from device-local complete-reverse files."""
        logger.info("Extracting Config variables from violation checks...")
        self.config_variables = []
        self.config_vars_by_name = {}
        self.config_vars_by_device = {}

        for device in self._devices_with_violation_check():
            logger.info(
                "Extracting Config variables from violation check for device: %s",
                device,
            )
            source_file = self._violation_check_path(device)
            device_variables = util_file.load_config_variables_from_smt(source_file)
            for config_var in device_variables:
                self.config_vars_by_name.setdefault(
                    config_var.name, []
                ).append(config_var)
                logger.info(
                    "    Found Config variable: %s = %s",
                    config_var.name,
                    config_var.value,
                )
            self.config_vars_by_device[device] = device_variables
            self.config_variables.extend(device_variables)
            logger.info(
                "Found %d Config variables in violation check for device %s",
                len(device_variables),
                device,
            )

        logger.info(
            "Total Config variable instances found: %d", len(self.config_variables)
        )
        logger.info("Unique Config variables found: %d", len(self.config_vars_by_name))
        for config_name, variables in self.config_vars_by_name.items():
            devices = {
                device
                for variable in variables
                if (device := get_device_for_config_var(variable, self.devices))
            }
            if devices:
                logger.info(
                    "  %s: found in %d violation checks: %s",
                    config_name,
                    len(variables),
                    sorted(devices),
                )
            else:
                logger.warning(
                    "  %s: found in %d violation checks, but could not "
                    "determine device names",
                    config_name,
                    len(variables),
                )

    def extract_line_level_config_groups(self) -> None:
        """Build line-level groups from device-local sliced SMT files."""
        logger.info("Extracting line-level config groups...")
        self.line_level_groups = {}
        sliced_dir = self.work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR

        for device in self._devices_with_sliced():
            logger.info("Extracting line-level config groups for device: %s", device)
            sliced_file = sliced_dir / util_file.router_local_encoding_file_name(device)
            by_prefix: Dict[str, List[ConfigVariable]] = {}
            for config_var in util_file.load_config_variables_from_smt(sliced_file):
                prefix = self._get_line_prefix_from_config_name(config_var.name)
                if prefix:
                    by_prefix.setdefault(prefix, []).append(config_var)
                    logger.info(
                        "    Found LineX config: %s = %s",
                        config_var.name,
                        config_var.value,
                    )

            groups: List[LineLevelConfigGroup] = []
            for prefix, variables in by_prefix.items():
                line_id = self._line_id_from_prefix(prefix)
                groups.append(
                    LineLevelConfigGroup(
                        device=device,
                        line_id=line_id,
                        config_variables=variables,
                        line_prefix=prefix,
                    )
                )
                logger.info(
                    "  Created line group: %s - %s with %d config variables",
                    device,
                    line_id,
                    len(variables),
                )
            self.line_level_groups[device] = groups
            logger.info(
                "Found %d line-level config groups for device %s",
                len(groups),
                device,
            )

        logger.info(
            "Total line-level config groups found: %d",
            sum(len(groups) for groups in self.line_level_groups.values()),
        )

    def _satisfaction_check_path(self, device: str) -> Path:
        return (
            self.work_dir
            / util_keyword.CONSISTENCY_CHECK_DIR
            / util_file.satisfaction_check_file_name(device)
        )

    def _violation_check_path(self, device: str) -> Path:
        return (
            self.work_dir
            / util_keyword.CONSISTENCY_CHECK_DIR
            / util_file.violation_check_file_name(device)
        )

    def _write_compute_smt2_field_level(
        self, config_var: ConfigVariable, device: str
    ) -> Optional[Path]:
        source_file = self._satisfaction_check_path(device)
        if not source_file.is_file():
            raise FileNotFoundError(
                f"Satisfaction check not found for {device}: {source_file}"
            )

        lines = util_file.load_text_lines(source_file, keepends=True)
        modified_lines, found = self._comment_config_var_equality_and_add_bounds(
            lines, config_var
        )
        if not found:
            raise ValueError(
                f"Config variable {config_var.name} not found in "
                f"{source_file}"
            )

        content = replace_check_sat_with_simplify("".join(modified_lines))
        safe_name = util_file.safe_filename_component(config_var.name)
        output_file = (
            self.field_level_intermediate_dir
            / f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        logger.info("    Synthesis subspec file saved to: %s", output_file)
        return output_file

    def _check_subspec_field_level(
        self, config_var: ConfigVariable, device: str
    ) -> bool:
        logger.info(
            "  Checking combined constraint negated impact for %s", config_var.name
        )
        return check_impact_forward(
            self._violation_check_path(device),
            [config_var],
            self.field_level_intermediate_dir,
            device,
            util_file.safe_filename_component(config_var.name),
            baseline_has_check_sat=True,
        )

    @staticmethod
    def _parse_simplification_output(
        output: str, config_var: ConfigVariable
    ) -> Optional[str]:
        logger.info("    Parsing simplification output for %s", config_var.name)
        subspec = extract_config_constraints_from_z3_goal(output, {config_var.name})
        if subspec:
            logger.info("    Config variable found in constraints: %s", subspec)
            return subspec
        fallback = f"(= {config_var.name} {config_var.value})"
        logger.info("    Config variable has unique value: %s", fallback)
        return fallback

    def _write_compute_smt2_line_level(self, line_group) -> Optional[Path]:
        source_file = self._satisfaction_check_path(line_group.device)
        if not source_file.is_file():
            raise FileNotFoundError(
                f"Satisfaction check not found for {line_group.device}: "
                f"{source_file}"
            )

        temp_path = Path(self._comment_out_line_group(str(source_file), line_group))
        try:
            content = replace_check_sat_with_simplify(util_file.load_text(temp_path))
        finally:
            util_file.delete_file(temp_path)
        safe_name = util_file.safe_filename_component(line_group.line_prefix)
        output_file = (
            self.line_level_intermediate_dir
            / f"compute_subspec_from_{line_group.device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        logger.info("    Compute subspec file saved to: %s", output_file)
        return output_file

    def _check_subspec_line_level(self, line_group) -> bool:
        logger.info(
            "  Checking combined constraint negated impact for line group: %s - %s",
            line_group.device,
            line_group.line_id,
        )
        return check_impact_forward(
            self._violation_check_path(line_group.device),
            line_group.config_variables,
            self.line_level_intermediate_dir,
            line_group.device,
            util_file.safe_filename_component(line_group.line_prefix),
            baseline_has_check_sat=True,
            write_mode=ImpactCheckWriteMode.TEMP_WITH_DEBUG,
            cleanup_after=True,
        )

    @staticmethod
    def _parse_line_group_simplification_output(
        output: str, line_group
    ) -> Optional[str]:
        logger.info(
            "    Parsing simplification output for line group: %s - %s",
            line_group.device,
            line_group.line_id,
        )
        return extract_constraints_with_original_values(
            output, line_group.config_variables, "Line group"
        )

    def _write_compute_smt2_field_level_pair(self, config_pair) -> Optional[Path]:
        device = get_device_for_config_var(config_pair.ip_var, self.devices)
        if not device:
            raise ValueError(
                f"Could not determine device for config pair "
                f"{config_pair.base_name}"
            )
        source_file = self._satisfaction_check_path(device)
        if not source_file.is_file():
            raise FileNotFoundError(
                f"Satisfaction check not found for {device}: {source_file}"
            )

        temp_path = Path(self._comment_out_config_pair(str(source_file), config_pair))
        try:
            content = replace_check_sat_with_simplify(util_file.load_text(temp_path))
        finally:
            util_file.delete_file(temp_path)
        safe_name = util_file.safe_filename_component(config_pair.base_name)
        output_file = (
            self.field_level_intermediate_dir
            / f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        logger.info("    Compute subspec file saved to: %s", output_file)
        return output_file

    def _check_subspec_field_level_pair(self, config_pair) -> bool:
        logger.info(
            "  Checking combined constraint negated impact for config pair: %s",
            config_pair.base_name,
        )
        device = get_device_for_config_var(config_pair.ip_var, self.devices)
        if not device:
            raise ValueError(
                f"Could not determine device for config pair "
                f"{config_pair.base_name}"
            )
        return check_impact_forward(
            self._violation_check_path(device),
            [config_pair.ip_var, config_pair.mask_var],
            self.field_level_intermediate_dir,
            device,
            util_file.safe_filename_component(config_pair.base_name),
            baseline_has_check_sat=True,
            write_mode=ImpactCheckWriteMode.TEMP_WITH_DEBUG,
            cleanup_after=True,
        )

    @staticmethod
    def _parse_config_pair_simplification_output(
        output: str, config_pair
    ) -> Optional[str]:
        logger.info(
            "    Parsing simplification output for config pair: %s",
            config_pair.base_name,
        )
        return extract_constraints_with_original_values(
            output,
            [config_pair.ip_var, config_pair.mask_var],
            "Config pair",
        )


def extract_constraints_with_original_values(
    z3_output: str,
    config_variables: Sequence[ConfigVariable],
    label: str,
) -> str:
    """Extract simplified constraints and restore variables eliminated by Z3."""
    config_names = {config_var.name for config_var in config_variables}
    subspec = extract_config_constraints_from_z3_goal(z3_output, config_names)
    parts = subspec_string_to_list(subspec) if subspec else []

    for config_var in config_variables:
        if any(config_var.name in part for part in parts):
            continue
        original = f"(= {config_var.name} {config_var.value})"
        parts.append(original)
        logger.info(
            "    Added original constraint for replaced variable %s: %s",
            config_var.name,
            original,
        )

    if parts:
        result = " AND ".join(parts)
        logger.info("    %s subspec (including replaced variables): %s", label, result)
        return result

    fallback = " AND ".join(
        f"(= {config_var.name} {config_var.value})"
        for config_var in config_variables
    )
    logger.info("    %s has unique values: %s", label, fallback)
    return fallback


@dataclass(frozen=True)
class ConfigLocationVar:
    """A Config_* variable at a configuration location (field / line / pair)."""
    name: str
    value: str


class ImpactCheckWriteMode(Enum):
    """Where to write the impact-check SMT2 file."""
    PERSISTENT = "persistent"
    TEMP_WITH_DEBUG = "temp_with_debug"


def _as_config_location_var(
    item: NamedValue,
) -> ConfigLocationVar:
    if isinstance(item, ConfigLocationVar):
        return item
    return ConfigLocationVar(name=item.name, value=item.value)


def comment_config_var_equality_and_add_bounds(
    lines: List[str], config_var: NamedValue
) -> Tuple[List[str], bool]:
    """Comment out one (= Config_... value) line and insert bounds for that variable."""
    modified_lines: List[str] = []
    config_line_found = False
    config_line_pattern = f"= {config_var.name} {config_var.value}"
    first_commented_index: Optional[int] = None
    for line in lines:
        if config_line_pattern in line and not line.strip().startswith(";"):
            modified_lines.append(f"; {line.strip()}\n")
            config_line_found = True
            if first_commented_index is None:
                first_commented_index = len(modified_lines) - 1
        else:
            modified_lines.append(line)
    bounds_to_add = get_bounds_for_single_config_variable(config_var.name)
    if bounds_to_add and first_commented_index is not None:
        insert_pos = first_commented_index + 1
        bounds_lines = [f"{x}\n" for x in bounds_to_add]
        modified_lines[insert_pos:insert_pos] = bounds_lines
    return modified_lines, config_line_found


def _insert_index_before_check_sat(lines: List[str]) -> int:
    """Index at which to insert material before ``(check-sat)``, else end of file."""
    for i, line in enumerate(lines):
        if line.strip() == util_keyword.SMT_CHECK_SAT:
            return i
    return len(lines)


def comment_out_config_vars_to_temp(
    baseline_path: Path,
    config_vars: Sequence[NamedValue],
    *,
    comment: bool = True,
) -> str:
    """Comment a location and add assignments/bounds missing from its baseline."""
    vars_list = [_as_config_location_var(v) for v in config_vars]
    lines = util_file.load_text_lines(baseline_path, keepends=True)
    modified_lines, commented_names, first_index = _rewrite_config_equalities(
        lines, vars_list, comment=comment
    )

    if comment and vars_list:
        extra_lines: List[str] = []
        for config_var in vars_list:
            if config_var.name in commented_names:
                continue
            extra_lines.append(
                f"; (assert (= {config_var.name} {config_var.value}))\n"
            )
            logger.info(
                "    No (= %s ...) equality in baseline (missing template?); "
                "recording commented assignment with resolved value %s",
                config_var.name,
                config_var.value,
            )

        bounds = get_bounds_for_multiple_config_variables(
            [v.name for v in vars_list]
        )
        extra_lines.extend(f"{bound}\n" for bound in bounds)

        if extra_lines:
            insert_pos = (
                first_index + 1
                if first_index is not None
                else _insert_index_before_check_sat(modified_lines)
            )
            modified_lines[insert_pos:insert_pos] = extra_lines

    temp_path = util_file.write_temporary_text(
        "".join(modified_lines), suffix=".smt2"
    )
    return str(temp_path)


def _rewrite_config_equalities(
    lines: Sequence[str],
    config_vars: Sequence[ConfigLocationVar],
    *,
    comment: bool,
) -> Tuple[List[str], List[str], Optional[int]]:
    """Comment or restore simple equalities for the selected Config variables."""
    names = [config_var.name for config_var in config_vars]
    rewritten: List[str] = []
    matched_names: List[str] = []
    first_index: Optional[int] = None

    for line in lines:
        content = line.strip()
        uncommented = content.removeprefix(";").strip()
        matched_name = next(
            (
                name
                for name in names
                if name in uncommented
                and uncommented.startswith("(assert (= Config_")
                and uncommented.endswith("))")
            ),
            None,
        )
        if matched_name is None:
            rewritten.append(line)
            continue

        if matched_name not in matched_names:
            matched_names.append(matched_name)
        if comment and not content.startswith(";"):
            rewritten.append(f"; {content}\n")
            if first_index is None:
                first_index = len(rewritten) - 1
        elif not comment and content.startswith(";"):
            rewritten.append(f"{uncommented}\n")
        else:
            rewritten.append(line)

    return rewritten, matched_names, first_index


def comment_existing_config_equalities_to_temp(
    baseline_path: Path,
    config_vars: Sequence[NamedValue],
    *,
    comment: bool = True,
) -> str:
    """Comment existing equalities and add bounds only for matched variables."""
    vars_list = [_as_config_location_var(var) for var in config_vars]
    lines = util_file.load_text_lines(baseline_path, keepends=True)
    modified_lines, matched_names, first_index = _rewrite_config_equalities(
        lines, vars_list, comment=comment
    )

    if comment and matched_names and first_index is not None:
        bounds = get_bounds_for_multiple_config_variables(matched_names)
        if bounds:
            insert_at = first_index + 1
            modified_lines[insert_at:insert_at] = [f"{bound}\n" for bound in bounds]

    temp_path = util_file.write_temporary_text(
        "".join(modified_lines), suffix=".smt2"
    )
    return str(temp_path)


def _finalize_forward_impact_content(
    content: str, *, baseline_has_check_sat: bool
) -> str:
    """4/5: baseline already has (check-sat). 6: append (check-sat) only."""
    if baseline_has_check_sat:
        return content if content.endswith("\n") else content + "\n"
    return append_check_sat(content)


def _write_impact_check_file(
    content: str,
    intermediate_dir: Path,
    device: str,
    safe_name: str,
    write_mode: ImpactCheckWriteMode,
) -> Optional[Path]:
    """Write impact-check SMT2; return path to pass to Z3."""
    check_path = intermediate_dir / f"check_subspec_from_{device}_{safe_name}.smt2"
    if write_mode == ImpactCheckWriteMode.PERSISTENT:
        util_file.write_text(check_path, content)
        logger.info("    Impact check file saved to: %s", check_path)
        return check_path

    temp_path = util_file.write_temporary_text(content, suffix=".smt2")
    util_file.write_text(check_path, content)
    logger.info("    Debug impact check file saved to: %s", check_path)
    return temp_path


def _build_impact_check_content_from_baseline(
    baseline_path: Path,
    config_vars: Sequence[NamedValue],
    write_mode: ImpactCheckWriteMode,
    finalize_content: Callable[[str], str],
) -> Tuple[Optional[str], bool]:
    """Return (final_content, any_config_found)."""
    if not baseline_path.is_file():
        raise FileNotFoundError(
            f"Impact-check baseline not found: {baseline_path}"
        )

    vars_list = [_as_config_location_var(v) for v in config_vars]

    if write_mode == ImpactCheckWriteMode.PERSISTENT:
        if len(vars_list) != 1:
            raise ValueError(
                "PERSISTENT write mode requires exactly one config variable"
            )
        lines = util_file.load_text_lines(baseline_path, keepends=True)
        modified_lines, found = comment_config_var_equality_and_add_bounds(
            lines, vars_list[0]
        )
        if not found:
            return None, False
        content = finalize_content("".join(modified_lines))
        return content, True

    temp_path = comment_out_config_vars_to_temp(baseline_path, vars_list, comment=True)
    try:
        raw = util_file.load_text(Path(temp_path))
        content = finalize_content(raw)
        return content, True
    finally:
        if temp_path:
            util_file.delete_file(temp_path)


def _run_impact_query(
    smt2_path: Path,
    *,
    cleanup_after: bool,
) -> bool:
    try:
        result = run_z3_file(smt2_path)
        is_sat, status = parse_z3_output(result)
        if status not in {"sat", "unsat"}:
            raise RuntimeError(status)
        if is_sat:
            logger.info("    Result: SAT (has impact, continue to subspec computation)")
        else:
            logger.info("    Result: UNSAT (no impact, empty subspec)")
        return is_sat
    except Exception as exc:
        raise RuntimeError(
            f"Failed impact check with {smt2_path}: {exc}"
        ) from exc
    finally:
        if cleanup_after and smt2_path:
            util_file.delete_file(smt2_path)


def _prepare_impact_query(
    baseline_path: Path,
    config_vars: Sequence[NamedValue],
    intermediate_dir: Path,
    device: str,
    safe_name: str,
    write_mode: ImpactCheckWriteMode,
    finalize_content: Callable[[str], str],
) -> Optional[Path]:
    content, found = _build_impact_check_content_from_baseline(
        baseline_path,
        config_vars,
        write_mode,
        finalize_content,
    )
    if not found or content is None:
        names = ", ".join(
            _as_config_location_var(variable).name
            for variable in config_vars
        )
        logger.info(
            "Config location not found in baseline (%s), assuming no impact",
            names,
        )
        return None
    return _write_impact_check_file(
        content, intermediate_dir, device, safe_name, write_mode
    )


def _run_z3_sat_only(smt2_path: Path, *, cleanup_after: bool) -> bool:
    return _run_impact_query(
        smt2_path, cleanup_after=cleanup_after
    )


def check_impact_forward(
    baseline_path: Path,
    config_vars: Sequence[NamedValue],
    intermediate_dir: Path,
    device: str,
    safe_name: str,
    *,
    baseline_has_check_sat: bool = True,
    write_mode: ImpactCheckWriteMode = ImpactCheckWriteMode.PERSISTENT,
    cleanup_after: bool = False,
) -> bool:
    """Return whether a configuration location affects violation satisfiability."""
    smt2_path = _prepare_impact_query(
        baseline_path,
        config_vars,
        intermediate_dir,
        device,
        safe_name,
        write_mode,
        lambda content: _finalize_forward_impact_content(
            content, baseline_has_check_sat=baseline_has_check_sat
        ),
    )
    if smt2_path is None:
        return False
    return _run_z3_sat_only(smt2_path, cleanup_after=cleanup_after)


def is_nonempty_subspec(subspec: Optional[str]) -> bool:
    """Return whether a subspec contains a constraint."""
    return bool(subspec and subspec.strip() and subspec != "empty")
