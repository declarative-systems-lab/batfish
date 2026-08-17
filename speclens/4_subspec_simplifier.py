#!/usr/bin/env python3
"""Stage 4: derive trie-aware field- and line-level subspecs.

The simplifier consumes router-local stage-3 assume/guarantee encodings.  Its
distinctive behavior is RouteFilterList trie post-processing and the optional
derivation of field constraints from previously computed line constraints.
Shared loading, impact checks, SMT execution, and persistence live in ``utils``.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from utils import util_file, util_keyword
from utils.util_data import (
    ConfigVariable,
    ConfigVariablePair,
    LineLevelConfigGroup,
    SubspecCliOptions,
)
from utils.util_file import (
    find_metadata_file,
    get_subspec_output_file_path,
    load_line_level_subspecs_from_file,
    load_target_dst_ip,
    save_line_level_subspecs,
    save_synthesis_metadata,
)
from utils.util_log import (
    exit_with_error,
    log_info,
    log_warning,
    verbose_info,
)
from utils.util_smt import (
    build_smt_simplify_command,
    extract_base_name_for_ip_mask,
    extract_community_lists_from_line_subspec,
    extract_config_constraints_from_z3_goal,
    extract_constraints_excluding_field,
    get_action_from_core_subspec,
    get_bounds_for_single_config_variable,
    get_device_for_config_var,
    get_mask_variable_names_from_pairs,
    is_ip_mask_pair,
    replace_config_variables_in_subspec,
    require_successful_z3_output,
    run_z3_file,
    run_z3_text,
    strip_subspec_suffixes,
    subspec_string_to_smt2_and,
    subspec_to_smt2_asserts,
)
from utils.util_subspec import (
    LocalAgSubspecSimplifierMixin,
    format_subspec_completion,
)
from utils.util_subspec_community import CommunitySubspecCalculator
from utils.util_subspec_joint import run_joint_multi_location_subspec


_ROUTE_FILTER_LINE_PATTERN = re.compile(
    r"(Config_\S+_RouteFilterList_\S+)__Line(\d+)$"
)
_CONFIG_NAME_PATTERN = re.compile(r"Config_[a-zA-Z0-9_-]+")


class SubspecSimplifier(LocalAgSubspecSimplifierMixin):
    """Calculate stage-4 trie-aware field- and line-level subspecs."""

    subspec_stage = 4
    persistent_metadata = True
    initialize_unmatched_communities = True

    def __init__(
        self,
        work_dir: Path,
        enable_community: bool = False,
        field_level_only: bool = False,
        line_level_only: bool = False,
        verbose: bool = False,
        device_filter: Optional[str] = None,
        from_line_subspec: bool = False,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.verbose = verbose
        self.device_filter = device_filter
        self.from_line_subspec = from_line_subspec
        self.enable_community = enable_community
        self.field_level_only = field_level_only
        self.line_level_only = line_level_only
        if self.field_level_only and self.line_level_only:
            raise ValueError("Cannot specify both -f and -l flags at the same time")

        self.temp_dir_obj = None
        self.devices: List[str] = []
        self.config_variables: List[ConfigVariable] = []
        self.config_variable_pairs: List[ConfigVariablePair] = []
        self.config_vars_by_name: Dict[str, List[ConfigVariable]] = {}
        self.config_vars_by_device: Dict[str, List[ConfigVariable]] = {}
        self.line_level_groups: Dict[str, List[LineLevelConfigGroup]] = {}

        self.subspecs: Dict[str, Set[str]] = {}
        self.pair_subspecs: Dict[str, Set[str]] = {}
        self.line_level_subspecs: Dict[str, Set[str]] = {}
        self.subspec_compute_summary: Dict[str, Dict[str, int]] = {}

        # A sliced RouteFilterList may begin after Line1.
        self._rfl_first_line_by_base: Dict[str, str] = {}
        self._rfl_existing_line_nums_by_base: Dict[str, List[int]] = {}
        self.key_prefixlists: Set[str] = set()
        self.key_prefixlists_by_base: Dict[str, List[int]] = {}

        self.community_calculator: Optional[CommunitySubspecCalculator] = None
        self.target_dst_ip = ""

    def load_inputs(self) -> None:
        """Validate and load all data required by the trie-aware workflow."""
        self._validate_input_files()
        # Metadata persists so a later field-only run can reuse line results.
        self._init_output_dirs()
        self.target_dst_ip = load_target_dst_ip(self.work_dir)
        (
            self.key_prefixlists,
            self.key_prefixlists_by_base,
        ) = util_file.load_key_prefixlists(self.work_dir)
        self.load_device_info()
        self.extract_config_variables()
        self.extract_ip_mask_pairs()

        verbose_info(
            self.verbose,
            "Loaded %d key prefixlist entries",
            len(self.key_prefixlists),
        )

    def _prepare_line_goal_metadata(
        self,
        line_group: LineLevelConfigGroup,
    ) -> Optional[Path]:
        """Persist and return metadata used by all goals for one line."""
        if not self.subspec_baseline_files_dir or not line_group.config_variables:
            return None
        safe_line_prefix = util_file.safe_filename_component(line_group.line_prefix)
        synthesis_file = (
            self.line_level_intermediate_dir
            / f"compute_subspec_from_{line_group.device}_{safe_line_prefix}.smt2"
        )
        util_file.require_file(
            synthesis_file,
            description="Synthesis subspec file",
        )
        save_synthesis_metadata(
            line_group.device,
            line_group.line_prefix,
            str(synthesis_file),
            self.subspec_baseline_files_dir,
            "line",
        )
        return find_metadata_file(
            line_group.line_prefix,
            line_group.device,
            "line",
            self.subspec_baseline_files_dir,
        )

    def _normalize_line_goal(
        self,
        goal: str,
        line_group: LineLevelConfigGroup,
        metadata_file: Optional[Path],
    ) -> str:
        """Normalize a line-level goal through the shared goal pipeline."""
        return self._normalize_simplification_goal(
            goal,
            metadata_file=metadata_file,
            config_name=line_group.line_prefix,
            is_field_level=False,
            is_pair=False,
            intermediate_dir=self.line_level_intermediate_dir,
        )

    def calculate_line_level_subspecs(self) -> None:
        """Compute selected line goals, then restore trie-derived results."""
        verbose_info(self.verbose, "Calculating line-level subspecs...")
        route_filter_lines = self._index_route_filter_lines()
        lines_to_compute = self._select_route_filter_lines(route_filter_lines)
        groups_to_compute = self._select_line_groups(lines_to_compute)
        self._record_line_compute_summary(groups_to_compute)

        for device in sorted(groups_to_compute):
            verbose_info(self.verbose, "Processing line groups for device: %s", device)
            for line_group in sorted(
                groups_to_compute[device], key=lambda group: group.line_prefix
            ):
                self._process_line_group(line_group)

        self._post_process_key_prefixlists_line_level()

    def _index_route_filter_lines(self) -> Dict[str, Set[str]]:
        """Index existing RouteFilterList lines and their first sliced line."""
        lines_by_base: Dict[str, Set[str]] = {}
        for line_groups in self.line_level_groups.values():
            for line_group in line_groups:
                match = _ROUTE_FILTER_LINE_PATTERN.fullmatch(
                    line_group.line_prefix
                )
                if match:
                    lines_by_base.setdefault(match.group(1), set()).add(
                        line_group.line_prefix
                    )

        self._rfl_first_line_by_base.clear()
        self._rfl_existing_line_nums_by_base.clear()
        for base_prefix, line_prefixes in lines_by_base.items():
            line_numbers = sorted(
                int(_ROUTE_FILTER_LINE_PATTERN.fullmatch(prefix).group(2))
                for prefix in line_prefixes
            )
            self._rfl_first_line_by_base[base_prefix] = (
                f"{base_prefix}__Line{line_numbers[0]}"
            )
            self._rfl_existing_line_nums_by_base[base_prefix] = line_numbers
        return lines_by_base

    def _select_route_filter_lines(
        self, lines_by_base: Dict[str, Set[str]]
    ) -> Set[str]:
        """Select trie lines that require direct SMT computation."""
        selected: Set[str] = set()
        for base_prefix, line_prefixes in lines_by_base.items():
            first_line = self._rfl_first_line_by_base[base_prefix]
            if base_prefix in self.key_prefixlists_by_base:
                key_lines = {
                    f"{base_prefix}__Line{line_number}"
                    for line_number in self.key_prefixlists_by_base[base_prefix]
                }
                selected.update(key_lines & line_prefixes)
                first_number = self._rfl_existing_line_nums_by_base[base_prefix][0]
                if min(self.key_prefixlists_by_base[base_prefix]) > first_number:
                    selected.add(first_line)
            else:
                selected.add(first_line)
        verbose_info(
            self.verbose,
            "Selected %d RouteFilterList lines for direct computation",
            len(selected),
        )
        return selected

    def _select_line_groups(
        self, route_filter_lines: Set[str]
    ) -> Dict[str, List[LineLevelConfigGroup]]:
        """Keep selected trie lines and every non-RouteFilterList line."""
        selected: Dict[str, List[LineLevelConfigGroup]] = {}
        for device, line_groups in self.line_level_groups.items():
            groups = [
                group
                for group in line_groups
                if not _ROUTE_FILTER_LINE_PATTERN.fullmatch(group.line_prefix)
                or group.line_prefix in route_filter_lines
            ]
            if groups:
                selected[device] = groups
        return selected

    def _record_line_compute_summary(
        self, groups_to_compute: Dict[str, List[LineLevelConfigGroup]]
    ) -> None:
        """Record unique line counts for the final computation summary."""
        all_prefixes = {
            group.line_prefix
            for groups in self.line_level_groups.values()
            for group in groups
        }
        computed_prefixes = {
            group.line_prefix
            for groups in groups_to_compute.values()
            for group in groups
        }
        rfl_total = sum(
            bool(_ROUTE_FILTER_LINE_PATTERN.fullmatch(prefix))
            for prefix in all_prefixes
        )
        rfl_compute = sum(
            bool(_ROUTE_FILTER_LINE_PATTERN.fullmatch(prefix))
            for prefix in computed_prefixes
        )
        other_total = len(all_prefixes) - rfl_total
        other_compute = len(computed_prefixes) - rfl_compute
        self.subspec_compute_summary["line"] = {
            "total": len(all_prefixes),
            "compute": len(computed_prefixes),
            "skipped": len(all_prefixes) - len(computed_prefixes),
            "rfl_total": rfl_total,
            "rfl_compute": rfl_compute,
            "other_total": other_total,
            "other_compute": other_compute,
        }

    def _process_line_group(self, line_group: LineLevelConfigGroup) -> None:
        """Check, compute, normalize, and store one line-level subspec."""
        line_key = line_group.line_prefix
        results = self.line_level_subspecs.setdefault(line_key, set())
        verbose_info(self.verbose, "Processing line group: %s", line_key)

        try:
            if self._is_single_unmatched_community_line(line_group):
                results.add("empty")
                return
            if not self._check_subspec_line_level(line_group):
                results.add("empty")
                return

            goal = self._compute_subspec_line_level(line_group)
            if not goal:
                return
            metadata_file = self._prepare_line_goal_metadata(line_group)
            goal = self._normalize_line_goal(goal, line_group, metadata_file)
            self._store_line_goal(line_group, goal, metadata_file)
        finally:
            self._cleanup_line_group(line_group)

    def _is_single_unmatched_community_line(
        self, line_group: LineLevelConfigGroup
    ) -> bool:
        return len(line_group.config_variables) == 1 and self._is_unmatched_community_var(
            line_group.config_variables[0].name
        )

    def _store_line_goal(
        self,
        line_group: LineLevelConfigGroup,
        goal: str,
        metadata_file: Optional[Path],
    ) -> None:
        """Store a regular goal or its optional community alternatives."""
        results = self.line_level_subspecs[line_group.line_prefix]
        calculator = self._get_community_calculator()
        community_variable = None
        if calculator:
            community_variable, _ = (
                calculator.find_line_variables(
                    line_group
                )
            )

        goals = [goal]
        if calculator and community_variable and goal != "empty":
            goals = [
                self._normalize_line_goal(item, line_group, metadata_file)
                for item in calculator.extend_line_subspec(
                    line_group, goal
                )
            ]
        for result in goals:
            stored_result = (
                result
                if result == "empty" or result.startswith("empty")
                else f"{result} [from {line_group.device}]"
            )
            self._add_subspec_dedup_by_core(
                results, stored_result
            )

    def _cleanup_line_group(self, line_group: LineLevelConfigGroup) -> None:
        safe_line = util_file.safe_filename_component(line_group.line_prefix)
        safe_variables = [
            util_file.safe_filename_component(variable.name)
            for variable in line_group.config_variables
        ]
        self._delete_intermediate_files_for_target(
            self.line_level_intermediate_dir,
            line_group.device,
            safe_line,
            extra_safe_names=safe_variables,
        )

    def _find_line_group(
        self, line_prefix: str
    ) -> Optional[LineLevelConfigGroup]:
        normalized_prefix = line_prefix.rstrip("_")
        for groups in self.line_level_groups.values():
            for group in groups:
                if group.line_prefix.rstrip("_") == normalized_prefix:
                    return group
        return None

    def _build_config_variable_mapping(
        self, source_prefix: str, target_prefix: str
    ) -> Dict[str, str]:
        """Map first-line fields to corresponding target-line fields."""
        source_group = self._find_line_group(source_prefix)
        target_group = self._find_line_group(target_prefix)
        if not source_group or not target_group:
            log_warning(
                "Cannot map RouteFilterList line %s to %s",
                source_prefix,
                target_prefix,
            )
            return {}

        targets_by_field = {
            variable.name.rpartition("_")[2]: variable.name
            for variable in target_group.config_variables
        }
        return {
            variable.name: targets_by_field[field]
            for variable in source_group.config_variables
            if (field := variable.name.rpartition("_")[2]) in targets_by_field
        }

    def _copy_first_line_subspecs(
        self, source_prefix: str, target_prefix: str
    ) -> Set[str]:
        """Copy first-line results while renaming their Config variables."""
        source_subspecs = self.line_level_subspecs.get(source_prefix)
        if source_subspecs is None:
            log_warning("First RouteFilterList line not found: %s", source_prefix)
            return set()
        variable_mapping = self._build_config_variable_mapping(
            source_prefix, target_prefix
        )
        return {
            subspec
            if subspec == "empty"
            or subspec.startswith("empty")
            or subspec.startswith("same_as_Line")
            else replace_config_variables_in_subspec(
                subspec, config_mapping=variable_mapping
            )
            for subspec in source_subspecs
        }

    def _extract_equality_constraints_from_sliced_file(
        self, target_line_prefix: str, device: str
    ) -> List[str]:
        """Load target-line equalities from one router-local encoding."""
        sliced_file = (
            self.work_dir
            / util_keyword.ROUTER_LOCAL_ENCODING_DIR
            / util_file.router_local_encoding_file_name(device)
        )
        util_file.require_file(
            sliced_file,
            description=f"Router-local encoding for device {device}",
        )
        return util_file.load_line_config_equalities(
            sliced_file, target_line_prefix
        )

    def _copy_first_line_metadata(
        self,
        source_file: Path,
        source_prefix: str,
        target_prefix: str,
        device: str,
    ) -> Path:
        """Copy first-line metadata while renaming target-line variables."""
        target_equalities = self._extract_equality_constraints_from_sliced_file(
            target_prefix, device
        )
        if not target_equalities:
            raise ValueError(
                f"No Config equalities found for copied RouteFilterList line "
                f"{target_prefix} on device {device}"
            )
        safe_target = util_file.safe_filename_component(target_prefix)
        output_file = self.subspec_baseline_files_dir / (
            f"synthesis_metadata_line_{device}_{safe_target}.txt"
        )
        util_file.copy_line_synthesis_metadata(
            source_file,
            output_file,
            source_prefix,
            target_prefix,
            target_equalities,
        )
        return util_file.require_file(
            output_file,
            description="Copied RouteFilterList line metadata",
        )

    def _first_line_context(
        self, first_line: str
    ) -> Tuple[Optional[str], Optional[Path]]:
        group = self._find_line_group(first_line)
        device = group.device if group else self._line_source_device(first_line, "")
        first_subspecs = self.line_level_subspecs.get(first_line, set())
        first_is_empty = not first_subspecs or all(
            subspec == "empty" or subspec.startswith("empty")
            for subspec in first_subspecs
        )
        if not device or first_is_empty:
            return device, None
        metadata_file = find_metadata_file(
            first_line,
            device,
            "line",
            self.subspec_baseline_files_dir,
        )
        return device, metadata_file

    def _copy_first_line_result(
        self,
        first_line: str,
        target_line: str,
        device: Optional[str],
        metadata_file: Optional[Path],
    ) -> None:
        copied_subspecs = self._copy_first_line_subspecs(
            first_line, target_line
        )
        self.line_level_subspecs[target_line] = copied_subspecs
        copied_is_empty = not copied_subspecs or all(
            subspec == "empty" or subspec.startswith("empty")
            for subspec in copied_subspecs
        )
        if copied_is_empty:
            return
        if not device:
            raise ValueError(
                f"Cannot determine device for copied RouteFilterList line "
                f"{target_line}"
            )
        if not metadata_file or not util_file.path_exists(metadata_file):
            raise FileNotFoundError(
                f"First-line metadata is required to generate metadata for "
                f"{target_line}: {metadata_file}"
            )
        self._copy_first_line_metadata(
            metadata_file, first_line, target_line, device
        )

    def _post_process_key_prefixlists_line_level(self) -> None:
        """Fill trie lines copied from or invalidated by key-prefix lines."""
        for base_prefix in sorted(self._rfl_existing_line_nums_by_base):
            existing_lines = self._rfl_existing_line_nums_by_base[base_prefix]
            first_line = self._rfl_first_line_by_base[base_prefix]
            device, metadata_file = self._first_line_context(first_line)
            key_lines = sorted(
                set(self.key_prefixlists_by_base.get(base_prefix, []))
                & set(existing_lines)
            )

            if not key_lines:
                for line_number in existing_lines[1:]:
                    self._copy_first_line_result(
                        first_line,
                        f"{base_prefix}__Line{line_number}",
                        device,
                        metadata_file,
                    )
                continue

            key_line_set = set(key_lines)
            last_key = key_lines[-1]
            for line_number in existing_lines[1:]:
                line_prefix = f"{base_prefix}__Line{line_number}"
                if line_number in key_line_set:
                    continue
                if line_number < last_key:
                    self._copy_first_line_result(
                        first_line,
                        line_prefix,
                        device,
                        metadata_file,
                    )
                else:
                    self.line_level_subspecs[line_prefix] = {"empty"}

    def _get_config_var_for_device(
        self, config_name: str, device: str
    ) -> Optional[ConfigVariable]:
        for config_variable in self.config_vars_by_name.get(config_name, []):
            if get_device_for_config_var(config_variable, self.devices) == device:
                return config_variable
        return None

    @staticmethod
    def _config_belongs_to_line_group(
        config_name: str, line_group_key: str
    ) -> bool:
        """Avoid treating ``__Line1`` as the prefix of ``__Line10``."""
        return config_name == line_group_key or config_name.startswith(line_group_key + "__")

    @staticmethod
    def _add_subspec_dedup_by_core(
        subspec_set: Set[str], new_subspec: str
    ) -> None:
        """Keep the first source annotation for each unique subspec core."""
        if new_subspec == "empty" or new_subspec.startswith("empty"):
            subspec_set.add(new_subspec)
            return
        core = new_subspec.rsplit(" [from ", 1)[0]
        for existing in subspec_set:
            if existing == "empty" or existing.startswith("empty"):
                continue
            existing_core = existing.rsplit(" [from ", 1)[0]
            if existing_core == core:
                return
        subspec_set.add(new_subspec)

    def calculate_field_level_from_line_level(self) -> None:
        """Project persisted line-level results onto their configuration fields."""
        verbose_info(
            self.verbose,
            "Calculating field-level subspecs from line-level subspecs...",
        )
        line_output_file = get_subspec_output_file_path(
            self.subspec_files_dir, "line", self.device_filter
        )
        if not util_file.path_exists(line_output_file):
            log_warning(
                "Line-level subspec file not found: %s. Run line-level first.",
                line_output_file,
            )
            return
        line_subspecs = load_line_level_subspecs_from_file(line_output_file)
        if not line_subspecs:
            log_warning("No line-level subspecs found in %s", line_output_file)
            return

        for line_key in sorted(line_subspecs):
            self._derive_fields_for_line(line_key, line_subspecs[line_key])

    def _derive_fields_for_line(
        self, line_key: str, line_subspecs: List[str]
    ) -> None:
        field_names = self._field_names_for_line(line_key)
        if not field_names:
            log_warning("No config variables for line group %s", line_key)
            return
        if not line_subspecs:
            for field_name in field_names:
                self.subspecs.setdefault(field_name, set()).add("empty")
            return

        device = self._line_source_device(line_key, line_subspecs[0])
        if not device:
            log_warning("Cannot determine device for line group %s", line_key)
            return
        if not self._load_field_line_metadata(line_key, device):
            return

        if len(field_names) == 1:
            self._derive_single_field_from_line(
                field_names[0], line_subspecs, device
            )
            return
        self._derive_multiple_fields_from_line(
            line_key, field_names, line_subspecs, device
        )

    def _field_names_for_line(self, line_key: str) -> List[str]:
        return sorted(
            name
            for name in self.config_vars_by_name
            if self._config_belongs_to_line_group(name, line_key)
        )

    @staticmethod
    def _split_source_annotation(subspec: str) -> Tuple[str, Optional[str]]:
        match = re.search(r" \[from (\S+)\]$", subspec)
        if not match:
            return subspec, None
        return subspec[: match.start()], match.group(1)

    def _line_source_device(
        self, line_key: str, subspec: str
    ) -> Optional[str]:
        _, source_device = self._split_source_annotation(subspec)
        if source_device:
            return source_device
        match = re.search(r"Config_([a-zA-Z0-9_-]+)_", line_key)
        return match.group(1) if match else None

    def _load_field_line_metadata(
        self, line_key: str, device: str
    ) -> Optional[Tuple[Path, List[str], List[str]]]:
        metadata_file = find_metadata_file(
            line_key,
            device,
            "line",
            self.subspec_baseline_files_dir,
        )
        if not metadata_file:
            log_warning(
                "Line-level metadata not found for %s on device %s",
                line_key,
                device,
            )
            return None
        declarations, equalities, _ = (
            util_file.load_synthesis_metadata_file(metadata_file)
        )
        if not declarations:
            log_warning("No declarations found in metadata file %s", metadata_file)
            return None
        return metadata_file, declarations, equalities

    def _derive_single_field_from_line(
        self,
        field_name: str,
        line_subspecs: List[str],
        fallback_device: str,
    ) -> None:
        for line_subspec in line_subspecs:
            clean_subspec, source_device = self._split_source_annotation(
                line_subspec
            )
            source_device = source_device or fallback_device
            core, _ = strip_subspec_suffixes(clean_subspec)
            field_subspec = self._merge_community_classification(
                field_name, core, clean_subspec
            )
            self._add_field_subspec(field_name, field_subspec, source_device)

    @staticmethod
    def _find_ip_mask_fields(
        field_names: List[str],
    ) -> Tuple[Dict[str, str], Set[str]]:
        pairs: Dict[str, str] = {}
        paired_fields: Set[str] = set()
        for index, first in enumerate(field_names):
            if first in paired_fields:
                continue
            for second in field_names[index + 1 :]:
                if second in paired_fields or not is_ip_mask_pair(first, second):
                    continue
                ip_field, mask_field = (
                    (first, second) if first.endswith("__ip") else (second, first)
                )
                pairs[ip_field] = mask_field
                paired_fields.update((ip_field, mask_field))
                break
        return pairs, paired_fields

    def _derive_multiple_fields_from_line(
        self,
        line_key: str,
        field_names: List[str],
        line_subspecs: List[str],
        fallback_device: str,
    ) -> None:
        ip_mask_pairs, paired_fields = self._find_ip_mask_fields(field_names)
        ordinary_fields = [
            name for name in field_names if name not in paired_fields
        ]

        for line_subspec in line_subspecs:
            _, source_device = self._split_source_annotation(line_subspec)
            source_device = source_device or fallback_device
            metadata = self._load_field_line_metadata(line_key, source_device)
            if not metadata:
                continue
            metadata_file, declarations, equalities = metadata
            if self.from_line_subspec:
                self._derive_fields_from_line_goal(
                    line_key,
                    field_names,
                    ip_mask_pairs,
                    ordinary_fields,
                    line_subspec,
                    source_device,
                    metadata_file,
                    declarations,
                    equalities,
                )
            else:
                self._derive_fields_from_consistency_checks(
                    ip_mask_pairs,
                    ordinary_fields,
                    source_device,
                )

        for field_name in [*ip_mask_pairs, *ordinary_fields]:
            results = self.subspecs.setdefault(field_name, set())
            if "empty" in results and any(item != "empty" for item in results):
                results.discard("empty")

    def _derive_fields_from_line_goal(
        self,
        line_key: str,
        field_names: List[str],
        ip_mask_pairs: Dict[str, str],
        ordinary_fields: List[str],
        line_subspec: str,
        device: str,
        metadata_file: Path,
        declarations: List[str],
        equalities: List[str],
    ) -> None:
        source_goal = [line_subspec]
        for ip_field, mask_field in ip_mask_pairs.items():
            is_empty = self._check_subspec_field_level_from_line_level(
                ip_field,
                field_names,
                source_goal,
                declarations,
                equalities,
                device,
            )
            if is_empty:
                self.subspecs.setdefault(ip_field, set()).add("empty")
                continue
            pair_subspec = self._compute_subspec_field_level_pair_from_line_level(
                line_key,
                ip_field,
                mask_field,
                field_names,
                source_goal,
                metadata_file,
                declarations,
                equalities,
                device,
            )
            if pair_subspec:
                pair_subspec = self._merge_community_classification(
                    ip_field, pair_subspec, line_subspec
                )
                self._add_field_subspec(ip_field, pair_subspec, device)
            safe_base = util_file.safe_filename_component(
                extract_base_name_for_ip_mask(ip_field)
            )
            self._delete_intermediate_files_for_target(
                self.field_level_intermediate_dir, device, safe_base
            )
            self._delete_metadata_file_for_target("pair", device, safe_base)

        for field_name in ordinary_fields:
            is_empty = self._check_subspec_field_level_from_line_level(
                field_name,
                field_names,
                source_goal,
                declarations,
                equalities,
                device,
            )
            if is_empty:
                self.subspecs.setdefault(field_name, set()).add("empty")
                continue
            field_subspec = self._compute_subspec_field_level_from_line_level(
                line_key,
                field_name,
                field_names,
                source_goal,
                metadata_file,
                declarations,
                equalities,
                device,
            )
            if field_subspec:
                field_subspec = self._merge_community_classification(
                    field_name, field_subspec, line_subspec
                )
                self._add_field_subspec(field_name, field_subspec, device)

    def _derive_fields_from_consistency_checks(
        self,
        ip_mask_pairs: Dict[str, str],
        ordinary_fields: List[str],
        device: str,
    ) -> None:
        for ip_field, mask_field in ip_mask_pairs.items():
            ip_variable = self._get_config_var_for_device(ip_field, device)
            mask_variable = self._get_config_var_for_device(mask_field, device)
            if not ip_variable or not mask_variable:
                log_warning(
                    "Config pair (%s, %s) not found for device %s",
                    ip_field,
                    mask_field,
                    device,
                )
                continue
            pair = ConfigVariablePair(
                ip_variable,
                mask_variable,
                extract_base_name_for_ip_mask(ip_field),
            )
            if not self._check_subspec_field_level_pair(pair):
                self.subspecs.setdefault(ip_field, set()).add("empty")
                continue
            pair_subspec = self._compute_subspec_field_level_pair(pair)
            if pair_subspec:
                pair_subspec = self._normalize_pair_subspec_with_metadata(
                    pair, pair_subspec, device
                )
                self._add_field_subspec(ip_field, pair_subspec, device)

        for field_name in ordinary_fields:
            config_variable = self._get_config_var_for_device(field_name, device)
            if not config_variable:
                log_warning(
                    "Config variable %s not found for device %s",
                    field_name,
                    device,
                )
                continue
            field_subspec = self._calculate_subspec_for_config_var(
                config_variable, device, field_name
            )
            if field_subspec:
                self._add_field_subspec(field_name, field_subspec, device)

    def _merge_community_classification(
        self, field_name: str, subspec: str, line_subspec: str
    ) -> str:
        calculator = self._get_community_calculator()
        if not (
            calculator
            and calculator.is_community_config_variable(field_name)
        ):
            return subspec
        clean_line, _ = self._split_source_annotation(line_subspec)
        community_lists = extract_community_lists_from_line_subspec(clean_line)
        if community_lists is None:
            return subspec

        core_line, _ = strip_subspec_suffixes(clean_line)
        action = get_action_from_core_subspec(core_line)
        configurable_permit, nonconfigurable_permit, configurable_deny, nonconfigurable_deny = (
            community_lists
        )
        if action is False:
            configurable = configurable_deny
            nonconfigurable = nonconfigurable_deny
        else:
            configurable = configurable_permit
            nonconfigurable = nonconfigurable_permit
        merged = calculator.append_classification(
            subspec,
            configurable,
            nonconfigurable,
            action_type=None,
        )
        return merged or subspec

    def _add_field_subspec(
        self, field_name: str, subspec: str, device: Optional[str]
    ) -> None:
        is_empty = subspec == "empty" or subspec.startswith("empty")
        result = subspec
        if not is_empty and device:
            result = f"{subspec} [from {device}]"
        values = self.subspecs.setdefault(field_name, set())
        self._add_subspec_dedup_by_core(values, result)
        if not is_empty:
            values.discard("empty")

    @classmethod
    def _first_line_goal(cls, line_subspecs: List[str]) -> Optional[str]:
        for subspec in line_subspecs:
            if subspec == "empty" or subspec.startswith("empty"):
                continue
            return cls._split_source_annotation(subspec)[0]
        return None

    @staticmethod
    def _parse_metadata_equalities(
        equalities: List[str],
    ) -> List[Tuple[str, str, str]]:
        """Return ``(Config name, assertion, assertion body)`` tuples."""
        parsed = []
        for equality in equalities:
            name_match = _CONFIG_NAME_PATTERN.search(equality)
            assertion = equality.lstrip(";").strip()
            if not name_match or not assertion.startswith("(assert"):
                continue
            body_match = re.match(r"\(assert\s+(.+)\)", assertion)
            if body_match:
                parsed.append(
                    (name_match.group(0), assertion, body_match.group(1))
                )
        return parsed

    @staticmethod
    def _single_equality_fallback(
        parsed_equalities: List[Tuple[str, str, str]], target_name: str
    ) -> Optional[str]:
        return next(
            (
                body
                for name, _, body in parsed_equalities
                if name == target_name
            ),
            None,
        )

    @classmethod
    def _pair_equality_fallback(
        cls,
        parsed_equalities: List[Tuple[str, str, str]],
        ip_name: str,
        mask_name: str,
    ) -> Optional[str]:
        ip_fallback = cls._single_equality_fallback(
            parsed_equalities, ip_name
        )
        mask_fallback = cls._single_equality_fallback(
            parsed_equalities, mask_name
        )
        if ip_fallback and mask_fallback:
            return f"(and {ip_fallback} {mask_fallback})"
        return None

    def _check_subspec_field_level_from_line_level(
        self,
        target_config_name: str,
        all_config_names: List[str],
        line_subspecs: List[str],
        declares: List[str],
        commented_equalities: List[str],
        device: str,
    ) -> bool:
        """Return whether other field equalities imply the line goal."""
        line_subspec = self._first_line_goal(line_subspecs)
        if not line_subspec:
            return True
        core_line = strip_subspec_suffixes(line_subspec)[0]
        line_subspec_smt2 = subspec_string_to_smt2_and(core_line)
        if not line_subspec_smt2:
            raise ValueError(
                f"Failed to convert line-level subspec to SMT2 for "
                f"{target_config_name} on device {device}"
            )
        target_fields_to_comment: Set[str] = {target_config_name}
        if target_config_name.endswith("__ip"):
            base_name = target_config_name[:-4]
            if base_name + "__mask" in all_config_names:
                target_fields_to_comment.add(base_name + "__mask")
        elif target_config_name.endswith("__mask"):
            base_name = target_config_name[:-6]
            if base_name + "__ip" in all_config_names:
                target_fields_to_comment.add(base_name + "__ip")

        parsed_equalities = self._parse_metadata_equalities(
            commented_equalities
        )
        smt2_content = [
            "; Check if field-level subspec is empty",
            f"; Target field: {target_config_name}",
            "",
            *sorted(set(declares)),
            "",
        ]
        all_bounds: Set[str] = set()
        for config_name, assertion, _ in parsed_equalities:
            smt2_content.append(f"; {assertion}")
            all_bounds.update(
                get_bounds_for_single_config_variable(config_name)
            )
        if all_bounds:
            smt2_content.append("")
            smt2_content.extend(sorted(all_bounds))
        smt2_content.extend(
            assertion
            for config_name, assertion, _ in parsed_equalities
            if config_name not in target_fields_to_comment
        )

        # Preserve line constraints that do not mention any Config field.
        line_conjuncts_no_config = extract_constraints_excluding_field(
            core_line, list(all_config_names)
        )
        if line_conjuncts_no_config:
            smt2_content.extend(
                [
                    "",
                    "; Constraints on other vars",
                    *(f"(assert {item})" for item in line_conjuncts_no_config),
                ]
            )
        check_assertion = f"(assert (not {line_subspec_smt2}))"
        missing_parentheses = check_assertion.count("(") - check_assertion.count(
            ")"
        )
        if missing_parentheses > 0:
            check_assertion += ")" * missing_parentheses
        smt2_content.extend(
            [
                "",
                check_assertion,
                "",
                util_keyword.SMT_CHECK_SAT,
            ]
        )
        content_str = "\n".join(smt2_content)
        safe_config_name = util_file.safe_filename_component(target_config_name)
        temporary_check_file = None
        if self.verbose:
            check_file = self.field_level_intermediate_dir / (
                f"check_subspec_from_{device}_{safe_config_name}.smt2"
            )
            util_file.write_text(check_file, content_str)
        else:
            check_file = util_file.write_temporary_text(
                content_str, suffix=".smt2"
            )
            temporary_check_file = check_file
        try:
            result = run_z3_file(check_file)
            output = require_successful_z3_output(
                result,
                f"field impact check {target_config_name} on device {device}",
            )
            status = next(
                (line.strip().lower() for line in output.splitlines() if line.strip()),
                "",
            )
            if status == "unsat":
                verbose_info(
                    self.verbose,
                    "Field %s is implied by other field equalities",
                    target_config_name,
                )
                return True
            if status == "sat":
                return False
            raise RuntimeError(
                f"Unexpected Z3 result for field impact check "
                f"{target_config_name} on device {device}: {status or output}"
            )
        except Exception as error:
            raise RuntimeError(
                f"Failed to check field {target_config_name} on device "
                f"{device}: {error}"
            ) from error
        finally:
            if temporary_check_file is not None:
                util_file.delete_file(temporary_check_file)

    def _compute_subspec_field_level_from_line_level(
        self,
        line_group_key: str,
        target_config_name: str,
        all_config_names: List[str],
        line_subspecs: List[str],
        metadata_file: Path,
        declares: List[str],
        commented_equalities: List[str],
        device: str,
    ) -> Optional[str]:
        """Simplify one field while all sibling fields remain concrete."""
        line_subspec = self._first_line_goal(line_subspecs)
        if not line_subspec:
            return None
        core_line = strip_subspec_suffixes(line_subspec)[0]
        line_asserts = [
            f"(assert {constraint})"
            for constraint in subspec_to_smt2_asserts(core_line)
        ]
        parsed_equalities = self._parse_metadata_equalities(
            commented_equalities
        )
        original_constraints = {
            name: body
            for name, _, body in parsed_equalities
            if name in all_config_names
        }
        fallback = self._single_equality_fallback(
            parsed_equalities, target_config_name
        )
        if fallback is None:
            raise ValueError(
                f"Original equality for {target_config_name} is missing from "
                f"metadata {metadata_file}"
            )
        smt_content = [
            "; Field-level from line-level",
            f"; Line group: {line_group_key}",
            f"; Target: {target_config_name}",
            "",
            *sorted(set(declares)),
            "",
            *line_asserts,
            "",
        ]
        all_bounds: Set[str] = set()
        for config_name, assertion, _ in parsed_equalities:
            smt_content.append(f"; {assertion}")
            all_bounds.update(
                get_bounds_for_single_config_variable(config_name)
            )
        if all_bounds:
            smt_content.append("")
            smt_content.extend(sorted(all_bounds))
        smt_content.extend(
            assertion
            for config_name, assertion, _ in parsed_equalities
            if config_name != target_config_name
        )
        smt_content.extend(["", build_smt_simplify_command()])
        safe_name = util_file.safe_filename_component(target_config_name)
        temp_path = self.field_level_intermediate_dir / (
            f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        smt_input = "\n".join(smt_content)
        util_file.write_text(temp_path, smt_input)
        try:
            result = run_z3_text(smt_input)
            output = require_successful_z3_output(
                result,
                f"field simplification {target_config_name} on device {device}",
            )
            field_subspec = extract_config_constraints_from_z3_goal(
                output,
                {target_config_name},
                original_constraints_map=original_constraints,
            )
            if field_subspec:
                return self._normalize_simplification_goal(
                    field_subspec,
                    metadata_file=metadata_file,
                    config_name=target_config_name,
                    is_field_level=True,
                    is_pair=False,
                    intermediate_dir=self.field_level_intermediate_dir,
                )
            return fallback
        except Exception as error:
            raise RuntimeError(
                f"Failed to simplify field {target_config_name} on device "
                f"{device}: {error}"
            ) from error

    def _compute_subspec_field_level_pair_from_line_level(
        self,
        line_group_key: str,
        ip_var_name: str,
        mask_var_name: str,
        all_config_names: List[str],
        line_subspecs: List[str],
        metadata_file: Path,
        declares: List[str],
        commented_equalities: List[str],
        device: str,
    ) -> Optional[str]:
        """Simplify an IP/mask pair while sibling fields remain concrete."""
        line_subspec = self._first_line_goal(line_subspecs)
        if not line_subspec:
            return None
        core_line = strip_subspec_suffixes(line_subspec)[0]
        line_asserts = [
            f"(assert {constraint})"
            for constraint in subspec_to_smt2_asserts(core_line)
        ]
        parsed_equalities = self._parse_metadata_equalities(
            commented_equalities
        )
        original_constraints = {
            name: body
            for name, _, body in parsed_equalities
            if name in all_config_names
        }
        fallback = self._pair_equality_fallback(
            parsed_equalities, ip_var_name, mask_var_name
        )
        if fallback is None:
            raise ValueError(
                f"Original equalities for pair ({ip_var_name}, {mask_var_name}) "
                f"are missing from metadata {metadata_file}"
            )
        target_names = {ip_var_name, mask_var_name}
        smt_content = [
            "; Field-level from line-level (ip-mask pair)",
            f"; Line group: {line_group_key}",
            "",
            *sorted(set(declares)),
            "",
            *line_asserts,
            "",
            *(
                f"; {assertion}"
                if config_name in target_names
                else assertion
                for config_name, assertion, _ in parsed_equalities
            ),
            "",
            build_smt_simplify_command(),
        ]
        safe_name = util_file.safe_filename_component(ip_var_name)
        temp_path = self.field_level_intermediate_dir / (
            f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        smt_input = "\n".join(smt_content)
        util_file.write_text(temp_path, smt_input)
        try:
            result = run_z3_text(smt_input)
            output = require_successful_z3_output(
                result,
                f"pair simplification ({ip_var_name}, {mask_var_name}) "
                f"on device {device}",
            )
            pair_subspec = extract_config_constraints_from_z3_goal(
                output,
                target_names,
                original_constraints_map=original_constraints,
            )
            if pair_subspec:
                return self._normalize_simplification_goal(
                    pair_subspec,
                    metadata_file=metadata_file,
                    config_name=ip_var_name,
                    is_field_level=True,
                    is_pair=True,
                    intermediate_dir=self.field_level_intermediate_dir,
                )
            return fallback
        except Exception as error:
            raise RuntimeError(
                f"Failed to simplify pair ({ip_var_name}, {mask_var_name}) "
                f"on device {device}: {error}"
            ) from error

    def run(self) -> None:
        """Run load, line projection, field projection, and persistence."""
        self.load_inputs()

        if not self.field_level_only:
            self.extract_line_level_config_groups()
            self.calculate_line_level_subspecs()
        if not self.line_level_only:
            # A field-only run reuses line output and persistent metadata.
            if not self.field_level_only:
                line_output_file = get_subspec_output_file_path(
                    self.subspec_files_dir, "line", self.device_filter
                )
                save_line_level_subspecs(
                    line_output_file, self.line_level_subspecs
                )
            self.calculate_field_level_from_line_level()

        self.save_results()


def _parse_cli_args(args: Sequence[str]) -> SubspecCliOptions:
    """Parse stage-4 command-line arguments."""
    delete_outputs = False
    field_level_only = False
    line_level_only = False
    verbose = False
    enable_community = False
    joint_multi_location = False
    from_line_subspec = False
    device_filter = None
    work_dir = None

    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "-d":
            delete_outputs = True
        elif argument == "-f":
            field_level_only = True
        elif argument == "-l":
            line_level_only = True
        elif argument == "-v":
            verbose = True
        elif argument == "-c":
            enable_community = True
        elif argument == "-m":
            joint_multi_location = True
        elif argument == "-o":
            from_line_subspec = True
        elif argument == "--device":
            index += 1
            if index >= len(args):
                raise ValueError("--device requires a device name")
            device_filter = args[index]
        elif argument.startswith("-"):
            raise ValueError(f"Unknown option: {argument}")
        elif work_dir is None:
            work_dir = Path(argument)
        else:
            raise ValueError("Multiple work directories specified")
        index += 1

    if field_level_only and line_level_only:
        raise ValueError("Cannot specify both -f and -l flags at the same time")
    if joint_multi_location and (
        field_level_only
        or line_level_only
        or from_line_subspec
        or enable_community
    ):
        raise ValueError("-m cannot be combined with -f, -l, -o, or -c")
    if work_dir is None:
        raise ValueError("Work directory not specified")

    return SubspecCliOptions(
        work_dir=work_dir,
        delete_outputs=delete_outputs,
        field_level_only=field_level_only,
        line_level_only=line_level_only,
        verbose=verbose,
        enable_community=enable_community,
        device_filter=device_filter,
        joint_multi_location=joint_multi_location,
        from_line_subspec=from_line_subspec,
    )


def _print_usage() -> None:
    print(
        "Usage: python 4_subspec_simplifier.py [-m] [-f] [-l] [-o] [-c] "
        "[-v] [-d] [--device DEVICE] <work_directory>"
    )
    print("Options:")
    print(
        "  -m           Joint multi-location subspec from "
        "0_multiple_locations.txt (per-slice, then AND non-empty joint subspec)"
    )
    print("  -f           Only calculate field-level subspecs")
    print("  -l           Only calculate line-level subspecs")
    print("  -c           Enable BitVec CommunityList classification")
    print(
        "  -o           When a line has multiple configs, build field-level "
        "checks from line-level subspec content"
    )
    print("  -v           Show detailed INFO logs and keep intermediate files")
    print("               Without -v: Show WARNING/ERROR logs and completion status")
    print("  -d           Delete all intermediate output files before running")
    print("  -h, --help   Show this help message")
    print("  --device     Process only the specified device")
    print("Example: python 4_subspec_simplifier.py smt_output_network_1")
    print("         python 4_subspec_simplifier.py -m smt_output_network_1")
    print("         python 4_subspec_simplifier.py -f smt_output_network_1")
    print("         python 4_subspec_simplifier.py -l smt_output_network_1")
    print("         python 4_subspec_simplifier.py -c smt_output_network_1")
    print("         python 4_subspec_simplifier.py -v smt_output_network_1")
    print("         python 4_subspec_simplifier.py -d smt_output_network_1")
    print("         python 4_subspec_simplifier.py --device r1 smt_output_network_1")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by stage 4 and report the result."""
    deleted_paths = util_file.delete_subspec_stage_outputs(
        work_dir,
        SubspecSimplifier.subspec_stage,
        include_joint=True,
    )
    if not deleted_paths:
        log_info("No intermediate files found to delete.")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted intermediate output: %s", deleted_path)


def _run_subspec_simplification(
    work_dir: Path,
    *,
    joint_multi_location: bool,
    field_level_only: bool,
    line_level_only: bool,
    from_line_subspec: bool,
    enable_community: bool,
    device_filter: Optional[str],
    verbose_flag: bool,
) -> Optional[SubspecSimplifier]:
    """Run the stage-4 joint or field/line subspec pipeline."""
    if joint_multi_location:
        run_joint_multi_location_subspec(
            work_dir,
            verbose=verbose_flag,
            device_filter=device_filter,
            intermediate_dir_name=util_file.intermediate_directory_name(
                4, util_keyword.INTERMEDIATE_JOINT_DIR_SUFFIX
            ),
            output_dir_name=util_keyword.SUBSPEC_DIR,
        )
        return None

    calculator = SubspecSimplifier(
        work_dir,
        enable_community=enable_community,
        field_level_only=field_level_only,
        line_level_only=line_level_only,
        verbose=verbose_flag,
        device_filter=device_filter,
        from_line_subspec=from_line_subspec,
    )
    calculator.run()
    return calculator


def main(args: Optional[Sequence[str]] = None) -> None:
    """Run the stage-4 subspec simplification pipeline."""
    cli_args = list(sys.argv[1:] if args is None else args)
    if any(argument in ("-h", "--help") for argument in cli_args):
        _print_usage()
        return
    if not cli_args:
        _print_usage()
        exit_with_error("Work directory is required")

    try:
        options = _parse_cli_args(cli_args)
    except ValueError as error:
        exit_with_error(f"Error: {error}")

    verbose_flag = options.verbose
    delete_flag = options.delete_outputs
    work_dir_path = options.work_dir
    joint_multi_location = options.joint_multi_location
    field_level_only = options.field_level_only
    line_level_only = options.line_level_only
    from_line_subspec = options.from_line_subspec
    enable_community = options.enable_community
    device_filter = options.device_filter

    if not work_dir_path.is_dir():
        _print_usage()
        exit_with_error(
            f"Work directory does not exist or is not a directory: "
            f"{work_dir_path}"
        )

    if delete_flag:
        _delete_outputs(work_dir_path)
        return

    try:
        calculator = _run_subspec_simplification(
            work_dir_path,
            joint_multi_location=joint_multi_location,
            field_level_only=field_level_only,
            line_level_only=line_level_only,
            from_line_subspec=from_line_subspec,
            enable_community=enable_community,
            device_filter=device_filter,
            verbose_flag=verbose_flag,
        )
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if not verbose_flag:
        if joint_multi_location:
            print("[✓] Completed: Joint Subspecification")
        else:
            if calculator is None:
                raise RuntimeError("Missing subspecification results")
            print(format_subspec_completion(calculator, "Subspecification"))


if __name__ == "__main__":
    main()
