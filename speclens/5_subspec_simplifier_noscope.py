#!/usr/bin/env python3
"""Stage 5: derive no-scope field- and line-level subspecifications.

Each configuration field, IP/mask pair, and line is analyzed independently
against the router-local satisfaction and violation encodings.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from utils import util_file, util_keyword
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
from utils.util_smt import get_device_for_config_var
from utils.util_subspec import (
    LocalAgSubspecSimplifierMixin,
    format_subspec_completion,
)
from utils.util_subspec_community import CommunitySubspecCalculator
from utils.util_subspec_joint import run_joint_multi_location_subspec


class NoScopeSubspecSimplifier(LocalAgSubspecSimplifierMixin):
    """Calculate Stage 5 subspecifications without trie-aware scoping."""

    subspec_stage = 5

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

        self.community_calculator: Optional[CommunitySubspecCalculator] = None
        self.target_dst_ip = ""

    def load_inputs(self) -> None:
        """Validate and load inputs shared by field- and line-level analysis."""
        self._validate_input_files()
        self._init_output_dirs()
        self.target_dst_ip = load_target_dst_ip(self.work_dir)
        self.load_device_info()
        self.extract_config_variables()
        self.extract_ip_mask_pairs()

    def _process_config_variable(
        self,
        config_name: str,
        config_variables: List[ConfigVariable],
        pair_variable_names: Set[str],
    ) -> None:
        """Calculate and merge every occurrence of one Config variable."""
        if config_name in pair_variable_names:
            return

        results = self.subspecs.setdefault(config_name, set())
        if self._is_unmatched_community_var(config_name):
            results.add("empty")
            return

        for config_var in config_variables:
            device = get_device_for_config_var(config_var, self.devices)
            if not device:
                raise ValueError(
                    f"Cannot determine device for Config variable {config_var.name}"
                )
            subspec = self._calculate_subspec_for_config_var(
                config_var, device, config_name
            )
            if subspec:
                results.add(subspec)

            safe_name = util_file.safe_filename_component(config_var.name)
            self._delete_intermediate_files_for_target(
                self.field_level_intermediate_dir,
                device,
                safe_name,
            )
            self._delete_metadata_file_for_target("field", device, safe_name)

    def calculate_field_level_subspecs(self) -> None:
        """Calculate independent Config-field and IP/mask-pair subspecs."""
        pair_variable_names = self._get_ip_mask_variable_names()
        for config_name in sorted(self.config_vars_by_name):
            self._process_config_variable(
                config_name,
                self.config_vars_by_name[config_name],
                pair_variable_names,
            )

        available_devices = set(self._devices_with_violation_check())
        pairs = sorted(self.config_variable_pairs, key=lambda pair: pair.base_name)
        for config_pair in pairs:
            device = get_device_for_config_var(config_pair.ip_var, self.devices)
            if not device:
                raise ValueError(
                    f"Cannot determine device for Config pair {config_pair.base_name}"
                )
            if device not in available_devices:
                raise ValueError(
                    f"Violation check is missing for Config pair "
                    f"{config_pair.base_name} on device {device}"
                )
            self._process_config_pair(config_pair, device)

    def _process_config_pair(
        self,
        config_pair: ConfigVariablePair,
        device: str,
    ) -> None:
        """Calculate, normalize, merge, and clean up one IP/mask pair."""
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
        if (
            len(line_group.config_variables) == 1
            and self._is_unmatched_community_var(
                line_group.config_variables[0].name
            )
        ):
            return {"empty"}
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
            line_groups = sorted(
                self.line_level_groups[device],
                key=lambda group: group.line_prefix,
            )
            for line_group in line_groups:
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
    """Parse Stage 5 command-line arguments."""
    delete_outputs = False
    field_level_only = False
    line_level_only = False
    verbose = False
    enable_community = False
    joint_multi_location = False
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
        field_level_only or line_level_only or enable_community
    ):
        raise ValueError("-m cannot be combined with -f, -l, or -c")
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
    )


def _print_usage() -> None:
    print(
        "Usage: python 5_subspec_simplifier_noscope.py [-m] [-f] [-l] [-c] "
        "[-v] [-d] [--device DEVICE] <work_directory>"
    )
    print("Options:")
    print("  -m           Calculate joint multi-location subspecifications")
    print("  -f           Only calculate field-level subspecifications")
    print("  -l           Only calculate line-level subspecifications")
    print("  -c           Enable BitVec CommunityList classification")
    print("  -v           Show detailed logs and keep intermediate files")
    print("  -d           Delete Stage 5 outputs and exit")
    print("  -h, --help   Show this help message")
    print("  --device     Process only the specified device")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by Stage 5."""
    deleted_paths = util_file.delete_subspec_stage_outputs(
        work_dir,
        NoScopeSubspecSimplifier.subspec_stage,
        include_joint=True,
    )
    if not deleted_paths:
        log_info("No Stage 5 outputs found to delete")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted output: %s", deleted_path)


def _run_subspec_simplification(
    work_dir: Path,
    *,
    joint_multi_location: bool,
    field_level_only: bool,
    line_level_only: bool,
    enable_community: bool,
    device_filter: Optional[str],
    verbose_flag: bool,
) -> Optional[NoScopeSubspecSimplifier]:
    """Run the Stage 5 joint or no-scope field/line pipeline."""
    if joint_multi_location:
        run_joint_multi_location_subspec(
            work_dir,
            verbose=verbose_flag,
            device_filter=device_filter,
            intermediate_dir_name=util_file.intermediate_directory_name(
                5, util_keyword.INTERMEDIATE_JOINT_DIR_SUFFIX
            ),
            output_dir_name=util_keyword.SUBSPEC_NOSCOPE_DIR,
        )
        return None

    calculator = NoScopeSubspecSimplifier(
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
    """Run the Stage 5 no-scope subspecification pipeline."""
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
            joint_multi_location=options.joint_multi_location,
            field_level_only=options.field_level_only,
            line_level_only=options.line_level_only,
            enable_community=options.enable_community,
            device_filter=options.device_filter,
            verbose_flag=options.verbose,
        )
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if options.verbose:
        return
    if options.joint_multi_location:
        print("[✓] Completed: Joint Subspecification")
        return
    if calculator is None:
        raise RuntimeError("Missing no-scope subspecification results")
    print(
        format_subspec_completion(
            calculator, "No-Scope Subspecification"
        )
    )


if __name__ == "__main__":
    main()
