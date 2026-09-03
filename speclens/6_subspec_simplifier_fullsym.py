#!/usr/bin/env python3
"""Stage 6: derive full-symbolic field- and line-level subspecifications.

Impact and subspecification are computed against two global router-local
encodings rather than independent per-device encodings.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from utils import util_file
from utils.util_data import (
    ConfigVariable,
    ConfigVariablePair,
    LineLevelConfigGroup,
    SubspecCliOptions,
)
from utils.util_file import (
    find_metadata_file,
    load_target_dst_ip,
    save_synthesis_metadata,
)
from utils.util_log import exit_with_error, log_info
from utils.util_smt import (
    extract_config_constraints_from_z3_goal,
    get_device_for_config_var,
    get_mask_variable_names_from_pairs,
    replace_check_sat_with_simplify,
)
from utils.util_subspec import (
    CommonSubspecSimplifierMixin,
    ImpactCheckWriteMode,
    check_impact_forward,
    extract_constraints_with_original_values,
    format_subspec_completion,
)
from utils.util_subspec_community import CommunitySubspecCalculator


class FullSymbolicSubspecSimplifier(CommonSubspecSimplifierMixin):
    """Calculate Stage 6 subspecifications from global symbolic baselines."""

    subspec_stage = 6

    def __init__(
        self,
        work_dir: Path,
        enable_community: bool = False,
        field_level_only: bool = False,
        line_level_only: bool = False,
        verbose: bool = False,
        device_filter: Optional[str] = None,
    ) -> None:
        self.work_dir = Path(work_dir)
        self.verbose = verbose
        self.device_filter = device_filter
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

        self.verification_baseline_file: Path
        self.subspec_baseline_file: Path
        self.community_calculator: Optional[CommunitySubspecCalculator] = None
        self.target_dst_ip = ""

    def load_inputs(self) -> None:
        """Validate and load the global full-symbolic inputs."""
        (
            self.verification_baseline_file,
            self.subspec_baseline_file,
        ) = util_file.validate_global_subspec_inputs(self.work_dir)
        self._init_output_dirs()
        self.target_dst_ip = load_target_dst_ip(self.work_dir)
        self.load_device_info()
        self.extract_config_variables()
        self.extract_ip_mask_pairs()

    def _get_community_calculator(self) -> Optional[CommunitySubspecCalculator]:
        """Lazily construct the optional full-symbolic community calculator."""
        if not self.enable_community:
            return None
        if self.community_calculator is None:
            self.community_calculator = CommunitySubspecCalculator(
                work_dir=self.work_dir,
                field_level_intermediate_dir=self.field_level_intermediate_dir,
                line_level_intermediate_dir=self.line_level_intermediate_dir,
                smt_source_file=self.subspec_baseline_file,
            )
        return self.community_calculator

    def load_device_info(self) -> None:
        """Load and optionally filter the canonical hostname list."""
        devices = util_file.load_hostnames(self.work_dir)
        if self.device_filter:
            if self.device_filter not in devices:
                raise ValueError(
                    f"Device '{self.device_filter}' is not present in "
                    f"the hostname file; available devices: "
                    f"{', '.join(devices)}"
                )
            devices = [self.device_filter]
        self.devices = devices

    def extract_config_variables(self) -> None:
        """Extract Config equalities from the global verification encoding."""
        self.config_variables = []
        self.config_vars_by_name = {}
        self.config_vars_by_device = {}

        loaded_variables = util_file.load_config_variables_from_smt(
            self.verification_baseline_file
        )
        for config_var in loaded_variables:
            device = get_device_for_config_var(config_var, self.devices)
            if self.device_filter and device != self.device_filter:
                continue
            if not device:
                raise ValueError(
                    f"Cannot determine device for Config variable {config_var.name}"
                )
            self.config_variables.append(config_var)
            self.config_vars_by_name.setdefault(config_var.name, []).append(
                config_var
            )
            self.config_vars_by_device.setdefault(device, []).append(config_var)

    def extract_line_level_config_groups(self) -> None:
        """Group global Config variables by device and Config line."""
        by_device: Dict[str, Dict[str, List[ConfigVariable]]] = {}
        for config_var in self.config_variables:
            line_prefix = self._get_line_prefix_from_config_name(config_var.name)
            if not line_prefix:
                continue
            device = get_device_for_config_var(config_var, self.devices)
            if not device:
                raise ValueError(
                    f"Cannot determine device for Config variable {config_var.name}"
                )
            by_device.setdefault(device, {}).setdefault(
                line_prefix, []
            ).append(config_var)

        self.line_level_groups = {}
        for device in sorted(by_device):
            groups = []
            for line_prefix in sorted(by_device[device]):
                groups.append(
                    LineLevelConfigGroup(
                        device=device,
                        line_id=self._line_id_from_prefix(line_prefix),
                        config_variables=by_device[device][line_prefix],
                        line_prefix=line_prefix,
                    )
                )
            self.line_level_groups[device] = groups

    def _calculate_config_result(
        self,
        config_var: ConfigVariable,
        device: str,
    ) -> Optional[str]:
        """Calculate and normalize one full-symbolic Config-field result."""
        if not self._check_subspec_field_level(config_var, device):
            return "empty"
        subspec = self._compute_subspec_field_level(config_var, device)
        if not subspec:
            return None

        metadata_file = self._prepare_metadata_file(config_var, device)
        normalized = self._normalize_subspec_with_metadata(
            subspec, config_var, metadata_file
        )
        calculator = self._get_community_calculator()
        if not (
            calculator
            and calculator.is_community_config_variable(config_var.name)
        ):
            return normalized

        extended = calculator.classify_values(
            config_var, device, normalized
        )
        if not extended:
            return normalized
        configurable, nonconfigurable = extended
        merged = calculator.append_classification(
            normalized, configurable, nonconfigurable
        )
        return (
            self._normalize_subspec_with_metadata(
                merged, config_var, metadata_file
            )
            if merged
            else normalized
        )

    def calculate_field_level_subspecs(self) -> None:
        """Calculate independent Config-field and IP/mask-pair subspecs."""
        pair_names = {
            name
            for pair in self.config_variable_pairs
            for name in (pair.ip_var.name, pair.mask_var.name)
        }
        for config_name in sorted(self.config_vars_by_name):
            if config_name in pair_names:
                continue
            results = self.subspecs.setdefault(config_name, set())
            for config_var in self.config_vars_by_name[config_name]:
                device = get_device_for_config_var(config_var, self.devices)
                if not device:
                    raise ValueError(
                        f"Cannot determine device for Config variable "
                        f"{config_var.name}"
                    )
                result = self._calculate_config_result(config_var, device)
                if result:
                    results.add(result)
                safe_name = util_file.safe_filename_component(config_var.name)
                self._delete_intermediate_files_for_target(
                    self.field_level_intermediate_dir,
                    device,
                    safe_name,
                )
                self._delete_metadata_file_for_target(
                    "field", device, safe_name
                )

        for config_pair in sorted(
            self.config_variable_pairs, key=lambda pair: pair.base_name
        ):
            self._process_config_pair(config_pair)

    def _process_config_pair(self, config_pair: ConfigVariablePair) -> None:
        """Calculate, normalize, merge, and clean up one IP/mask pair."""
        device = get_device_for_config_var(config_pair.ip_var, self.devices)
        if not device:
            raise ValueError(
                f"Cannot determine device for Config pair {config_pair.base_name}"
            )

        results = self.pair_subspecs.setdefault(config_pair.base_name, set())
        if not self._check_subspec_field_level_pair(config_pair):
            results.add("empty")
        else:
            subspec = self._compute_subspec_field_level_pair(config_pair)
            if subspec:
                results.add(
                    self._normalize_pair_subspec_with_metadata(
                        config_pair, subspec, device
                    )
                )
        self._merge_pair_subspecs_into_field(config_pair)
        self._cleanup_pair_subspec_files(config_pair, device)

    def _prepare_line_metadata(
        self,
        line_group: LineLevelConfigGroup,
    ) -> Optional[Path]:
        """Persist metadata for normalization of one line-level result."""
        if not self.subspec_baseline_files_dir or not line_group.config_variables:
            return None
        safe_name = util_file.safe_filename_component(line_group.line_prefix)
        synthesis_file = (
            self.line_level_intermediate_dir
            / f"compute_subspec_from_{line_group.device}_{safe_name}.smt2"
        )
        util_file.require_file(synthesis_file, description="Compute subspec file")
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

    def _normalize_line_subspec(
        self,
        subspec: str,
        line_group: LineLevelConfigGroup,
        metadata_file: Optional[Path],
    ) -> str:
        """Normalize one line-level simplification goal."""
        return self._normalize_simplification_goal(
            subspec,
            metadata_file=metadata_file,
            config_name=line_group.line_prefix,
            is_field_level=False,
            is_pair=False,
            intermediate_dir=self.line_level_intermediate_dir,
        )

    def _calculate_line_results(
        self,
        line_group: LineLevelConfigGroup,
    ) -> Set[str]:
        """Calculate the base or community-expanded results for one line."""
        if not self._check_subspec_line_level(line_group):
            return {"empty"}
        subspec = self._compute_subspec_line_level(line_group)
        if not subspec:
            return set()

        metadata_file = self._prepare_line_metadata(line_group)
        normalized = self._normalize_line_subspec(
            subspec, line_group, metadata_file
        )
        calculator = self._get_community_calculator()
        if not calculator or normalized == "empty":
            return {normalized}
        community_var, _ = (
            calculator.find_line_variables(
                line_group
            )
        )
        if not community_var:
            return {normalized}
        return {
            self._normalize_line_subspec(
                community_subspec, line_group, metadata_file
            )
            for community_subspec in (
                calculator.extend_line_subspec(
                    line_group, normalized
                )
            )
        }

    def calculate_line_level_subspecs(self) -> None:
        """Calculate independent subspecifications for every Config line."""
        for device in sorted(self.line_level_groups):
            for line_group in self.line_level_groups[device]:
                self.line_level_subspecs.setdefault(
                    line_group.line_prefix, set()
                ).update(self._calculate_line_results(line_group))
                self._cleanup_line_files(line_group)

    def _cleanup_line_files(self, line_group: LineLevelConfigGroup) -> None:
        """Remove temporary SMT files associated with one Config line."""
        safe_name = util_file.safe_filename_component(line_group.line_prefix)
        extra_names = [
            util_file.safe_filename_component(config_var.name)
            for config_var in line_group.config_variables
        ]
        self._delete_intermediate_files_for_target(
            self.line_level_intermediate_dir,
            line_group.device,
            safe_name,
            extra_safe_names=extra_names,
        )

    def _write_compute_smt2_field_level(
        self,
        config_var: ConfigVariable,
        device: str,
    ) -> Path:
        lines = util_file.load_text_lines(
            self.subspec_baseline_file, keepends=True
        )
        modified_lines, found = (
            self._comment_config_var_equality_and_add_bounds(lines, config_var)
        )
        if not found:
            raise ValueError(
                f"Config variable {config_var.name} is missing from subspecification "
                f"baseline {self.subspec_baseline_file}"
            )
        content = replace_check_sat_with_simplify("".join(modified_lines))
        safe_name = util_file.safe_filename_component(config_var.name)
        output_file = (
            self.field_level_intermediate_dir
            / f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        return output_file

    def _check_subspec_field_level(
        self,
        config_var: ConfigVariable,
        device: str,
    ) -> bool:
        return check_impact_forward(
            self.verification_baseline_file,
            [config_var],
            self.field_level_intermediate_dir,
            device,
            util_file.safe_filename_component(config_var.name),
            baseline_has_check_sat=False,
        )

    @staticmethod
    def _parse_simplification_output(
        output: str,
        config_var: ConfigVariable,
    ) -> str:
        subspec = extract_config_constraints_from_z3_goal(
            output, {config_var.name}
        )
        return subspec or f"(= {config_var.name} {config_var.value})"

    def _write_compute_smt2_line_level(
        self,
        line_group: LineLevelConfigGroup,
    ) -> Path:
        temp_path = Path(
            self._comment_out_line_group(
                str(self.subspec_baseline_file), line_group
            )
        )
        try:
            content = replace_check_sat_with_simplify(
                util_file.load_text(temp_path)
            )
        finally:
            util_file.delete_file(temp_path)
        safe_name = util_file.safe_filename_component(line_group.line_prefix)
        output_file = (
            self.line_level_intermediate_dir
            / f"compute_subspec_from_{line_group.device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        return output_file

    def _check_subspec_line_level(
        self,
        line_group: LineLevelConfigGroup,
    ) -> bool:
        return check_impact_forward(
            self.verification_baseline_file,
            line_group.config_variables,
            self.line_level_intermediate_dir,
            line_group.device,
            util_file.safe_filename_component(line_group.line_prefix),
            baseline_has_check_sat=False,
            write_mode=ImpactCheckWriteMode.TEMP_WITH_DEBUG,
            cleanup_after=True,
        )

    @staticmethod
    def _parse_line_group_simplification_output(
        output: str,
        line_group: LineLevelConfigGroup,
    ) -> str:
        return extract_constraints_with_original_values(
            output,
            line_group.config_variables,
            "Line group",
        )

    def _write_compute_smt2_field_level_pair(
        self,
        config_pair: ConfigVariablePair,
    ) -> Path:
        device = get_device_for_config_var(config_pair.ip_var, self.devices)
        if not device:
            raise ValueError(
                f"Cannot determine device for Config pair {config_pair.base_name}"
            )
        temp_path = Path(
            self._comment_out_config_pair(
                str(self.subspec_baseline_file), config_pair
            )
        )
        try:
            content = replace_check_sat_with_simplify(
                util_file.load_text(temp_path)
            )
        finally:
            util_file.delete_file(temp_path)
        safe_name = util_file.safe_filename_component(config_pair.base_name)
        output_file = (
            self.field_level_intermediate_dir
            / f"compute_subspec_from_{device}_{safe_name}.smt2"
        )
        util_file.write_text(output_file, content)
        return output_file

    def _check_subspec_field_level_pair(
        self,
        config_pair: ConfigVariablePair,
    ) -> bool:
        device = get_device_for_config_var(config_pair.ip_var, self.devices)
        if not device:
            raise ValueError(
                f"Cannot determine device for Config pair {config_pair.base_name}"
            )
        return check_impact_forward(
            self.verification_baseline_file,
            [config_pair.ip_var, config_pair.mask_var],
            self.field_level_intermediate_dir,
            device,
            util_file.safe_filename_component(config_pair.base_name),
            baseline_has_check_sat=False,
            write_mode=ImpactCheckWriteMode.TEMP_WITH_DEBUG,
            cleanup_after=True,
        )

    @staticmethod
    def _parse_config_pair_simplification_output(
        output: str,
        config_pair: ConfigVariablePair,
    ) -> str:
        return extract_constraints_with_original_values(
            output,
            [config_pair.ip_var, config_pair.mask_var],
            "Config pair",
        )

    def save_results(self) -> None:
        """Persist full-symbolic field- and line-level reports."""
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
            util_file.save_full_symbolic_field_level_subspecs(
                field_output_file, self.subspecs, mask_names
            )
        if not self.field_level_only:
            line_output_file = util_file.get_subspec_output_file_path(
                self.subspec_files_dir, "line", self.device_filter
            )
            util_file.save_full_symbolic_line_level_subspecs(
                line_output_file, self.line_level_subspecs
            )

    def run(self) -> None:
        """Run load, extraction, calculation, and persistence."""
        self.load_inputs()
        if not self.line_level_only:
            self.calculate_field_level_subspecs()
        if not self.field_level_only:
            self.extract_line_level_config_groups()
            self.calculate_line_level_subspecs()
        self.save_results()


def _parse_cli_args(args: Sequence[str]) -> SubspecCliOptions:
    """Parse Stage 6 command-line arguments."""
    delete_outputs = False
    field_level_only = False
    line_level_only = False
    verbose = False
    enable_community = False
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
    )


def _print_usage() -> None:
    print(
        "Usage: python 6_subspec_simplifier_fullsym.py [-f] [-l] [-c] [-v] "
        "[-d] [--device DEVICE] <work_directory>"
    )
    print("Options:")
    print("  -f           Only calculate field-level subspecifications")
    print("  -l           Only calculate line-level subspecifications")
    print("  -c           Enable BitVec CommunityList classification")
    print("  -v           Show detailed logs and keep intermediate files")
    print("  -d           Delete Stage 6 outputs and exit")
    print("  -h, --help   Show this help message")
    print("  --device     Process only the specified device")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by Stage 6."""
    deleted_paths = util_file.delete_subspec_stage_outputs(
        work_dir, FullSymbolicSubspecSimplifier.subspec_stage
    )
    if not deleted_paths:
        log_info("No Stage 6 outputs found to delete")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted output: %s", deleted_path)


def _run_subspec_simplification(
    work_dir: Path,
    *,
    field_level_only: bool,
    line_level_only: bool,
    enable_community: bool,
    device_filter: Optional[str],
    verbose_flag: bool,
) -> FullSymbolicSubspecSimplifier:
    """Run the Stage 6 full-symbolic field/line pipeline."""
    calculator = FullSymbolicSubspecSimplifier(
        work_dir,
        enable_community=enable_community,
        field_level_only=field_level_only,
        line_level_only=line_level_only,
        verbose=verbose_flag,
        device_filter=device_filter,
    )
    calculator.run()
    return calculator


def main(args: Optional[Sequence[str]] = None) -> None:
    """Run the Stage 6 full-symbolic subspecification pipeline."""
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

    if not options.work_dir.is_dir():
        exit_with_error(
            f"Work directory does not exist or is not a directory: "
            f"{options.work_dir}"
        )
    if options.delete_outputs:
        _delete_outputs(options.work_dir)
        return

    try:
        calculator = _run_subspec_simplification(
            options.work_dir,
            field_level_only=options.field_level_only,
            line_level_only=options.line_level_only,
            enable_community=options.enable_community,
            device_filter=options.device_filter,
            verbose_flag=options.verbose,
        )
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if not options.verbose:
        print(
            format_subspec_completion(
                calculator, "Full-Symbolic Subspecification"
            )
        )


if __name__ == "__main__":
    main()
