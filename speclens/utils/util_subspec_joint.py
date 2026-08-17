"""Compute and render joint subspecifications across configuration locations."""

from __future__ import annotations

import re
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from utils import util_file, util_keyword
from utils.util_log import get_logger
from utils.util_norm import normalize_subspec
from utils.util_smt import (
    extract_config_constraints_from_z3_goal,
    partition_configs_by_z3_goal_connectivity,
    replace_check_sat_with_simplify,
    require_successful_z3_output,
    run_z3_file,
    strip_subspec_suffixes,
    subspec_string_to_list,
)
from utils.util_subspec import (
    ConfigLocationVar,
    ImpactCheckWriteMode,
    check_impact_forward,
    comment_out_config_vars_to_temp,
    is_nonempty_subspec,
)

logger = get_logger(__name__)

CONFIG_EQ_RE = re.compile(r"^;?\s*\(assert \(= (Config_\S+) (\S+)\)\)")
CONFIG_SYMBOL_RE = re.compile(r"Config_[^\s()|]+")


@dataclass
class JointGroupResult:
    """One joint/singleton group (per-slice or necessary multi-slice AND)."""
    hosts: List[str]
    config_names: List[str]
    subspec: str  # "empty" or constraint string joined by " AND "

    @property
    def is_multi_config(self) -> bool:
        return len(self.config_names) >= 2


@dataclass
class SliceJointResult:
    """Joint subspec result for one AG slice host (possibly multiple CC groups)."""
    host: str
    locations: List[ConfigLocationVar]
    groups: List[JointGroupResult] = field(default_factory=list)

    @property
    def is_empty_slice(self) -> bool:
        return (not self.groups) or all(
            not is_nonempty_subspec(g.subspec) for g in self.groups
        )


@dataclass
class JointMultiLocationResult:
    """Full joint multi-location run result."""
    locations: List[str]
    per_slice: List[SliceJointResult] = field(default_factory=list)
    empty_configs: List[str] = field(default_factory=list)
    # Necessary AND merges: same inseparable multi-config set on >= 2 slices.
    merged_groups: List[JointGroupResult] = field(default_factory=list)

    @property
    def empty_slices(self) -> List[SliceJointResult]:
        return [r for r in self.per_slice if r.is_empty_slice]

    @property
    def nonempty_slices(self) -> List[SliceJointResult]:
        return [r for r in self.per_slice if not r.is_empty_slice]


def collect_empty_configs(
    locations: Sequence[str],
    per_slice: Sequence[SliceJointResult],
) -> List[str]:
    """Return locations that are empty on every matching slice."""
    empty: List[str] = []
    for name in locations:
        hit_slices = [
            r for r in per_slice if any(v.name == name for v in r.locations)
        ]
        if not hit_slices:
            empty.append(name)
            continue
        nonempty_hit = False
        for r in hit_slices:
            groups_with_name = [g for g in r.groups if name in g.config_names]
            if any(is_nonempty_subspec(g.subspec) for g in groups_with_name):
                nonempty_hit = True
                break
        if not nonempty_hit:
            empty.append(name)
    return empty


def load_multiple_locations(work_dir: Path) -> List[str]:
    """Load Config_* names from 0_multiple_locations.txt (one per line)."""
    path = work_dir / util_keyword.MULTIPLE_LOCATIONS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Multiple locations file not found: {path}")

    locations: List[str] = []
    seen: Set[str] = set()
    for line_num, line in enumerate(util_file.load_text_lines(path), 1):
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        if not name.startswith("Config_"):
            raise ValueError(
                f"Invalid location in {path} at line {line_num}: "
                f"expected Config_* name, got {name!r}"
            )
        if name in seen:
            continue
        seen.add(name)
        locations.append(name)
    if not locations:
        raise ValueError(f"No Config_* locations found in {path}")
    logger.info("Loaded %d locations from %s", len(locations), path)
    return locations


def list_ag_slice_hosts(
    work_dir: Path, device_filter: Optional[str] = None
) -> List[str]:
    """Return consistency-check hosts, falling back to router-local encodings."""
    ag_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    hosts: List[str] = []
    if ag_dir.exists():
        for path in sorted(
            ag_dir.glob(
                f"{util_keyword.VIOLATION_CHECK_FILE_PREFIX}_*.smt2"
            )
        ):
            host = path.name[
                len(util_keyword.VIOLATION_CHECK_FILE_PREFIX) + 1 : -len(".smt2")
            ]
            if host:
                hosts.append(host)
    if not hosts:
        encoding_dir = work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR
        if encoding_dir.exists():
            pattern = f"{util_keyword.LOCAL_ENCODING_FILE_PREFIX}_*.smt2"
            for path in sorted(encoding_dir.glob(pattern)):
                host = path.name[
                    len(util_keyword.LOCAL_ENCODING_FILE_PREFIX) + 1 : -len(".smt2")
                ]
                if host:
                    hosts.append(host)

    if device_filter is not None:
        if device_filter not in hosts:
            raise ValueError(
                f"Device '{device_filter}' not found among consistency-check "
                f"or router-local hosts: {hosts}"
            )
        hosts = [device_filter]

    if not hosts:
        raise FileNotFoundError(
            f"No AG slice hosts found under {ag_dir} "
            f"(or {work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR})"
        )
    return hosts


def locations_in_slice(
    locations: Sequence[str],
    work_dir: Path,
    host: str,
) -> List[str]:
    """Return locations present in the preferred encoding for one slice."""
    reverse_path = (
        work_dir
        / util_keyword.CONSISTENCY_CHECK_DIR
        / util_file.violation_check_file_name(host)
    )
    forward_path = (
        work_dir
        / util_keyword.CONSISTENCY_CHECK_DIR
        / util_file.satisfaction_check_file_name(host)
    )
    sliced_path = (
        work_dir
        / util_keyword.ROUTER_LOCAL_ENCODING_DIR
        / util_file.router_local_encoding_file_name(host)
    )

    # Prefer violation content; accept satisfaction/sliced content if absent.
    scan_paths = [p for p in (reverse_path, forward_path, sliced_path) if p.exists()]
    if not scan_paths:
        return []

    # Use reverse if present, else first available — ownership by content of the
    # primary AG reverse file when available (matches 4_ impact baseline).
    primary = reverse_path if reverse_path.exists() else scan_paths[0]
    symbols = set(CONFIG_SYMBOL_RE.findall(util_file.load_text(primary)))
    return [name for name in locations if name in symbols]


def resolve_config_vars_in_file(
    smt_path: Path,
    config_names: Sequence[str],
) -> List[ConfigLocationVar]:
    """Resolve (= Config_xxx value) for the given names from an SMT file."""
    wanted = set(config_names)
    found: Dict[str, str] = {}
    if not smt_path.exists():
        return []
    for line in util_file.load_text_lines(smt_path):
            m = CONFIG_EQ_RE.search(line.strip())
            if not m:
                continue
            name, value = m.group(1), m.group(2)
            if name in wanted and name not in found:
                found[name] = value
    missing = [n for n in config_names if n not in found]
    if missing:
        logger.warning(
            "Could not resolve equality values in %s for: %s",
            smt_path.name,
            ", ".join(missing),
        )
    # Preserve input order
    return [
        ConfigLocationVar(name=n, value=found[n])
        for n in config_names
        if n in found
    ]


def _restore_propagated_equalities(
    subspec: Optional[str],
    config_vars: Sequence[ConfigLocationVar],
) -> str:
    """Ensure every location Config_* appears; append equality if missing."""
    if subspec:
        parts = subspec_string_to_list(subspec)
    else:
        parts = []

    for config_var in config_vars:
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
        return " AND ".join(parts)

    # Fallback: all original equalities
    return " AND ".join(f"(= {v.name} {v.value})" for v in config_vars)


def _run_z3_simplify(smt2_path: Path, log_label: str) -> str:
    try:
        result = run_z3_file(smt2_path)
        output = require_successful_z3_output(
            result, f"joint simplification {log_label}"
        )
        logger.info("    Z3 Simplification Results for %s:", log_label)
        logger.info("    %s", "=" * 60)
        for line in output.split("\n"):
            logger.info("    %s", line)
        logger.info("    %s", "=" * 60)
        return output
    except Exception as exc:
        raise RuntimeError(
            f"Failed to simplify joint subspec {log_label} from {smt2_path}: "
            f"{exc}"
        ) from exc


def _group_safe_name(config_names: Sequence[str], index: int) -> str:
    """Short filesystem-safe identifier for a joint group."""
    if len(config_names) == 1:
        raw = config_names[0]
    else:
        raw = f"g{index}_{len(config_names)}cfgs"
    safe = re.sub(r"[^\w.-]", "_", raw)
    return safe[:120] if len(safe) > 120 else safe


def _normalize_joint_group_subspec(
    subspec: str,
    host: str,
    safe_name: str,
    compute_smt2_path: Path,
    intermediate_dir: Path,
    *,
    group_config_names: Sequence[str],
    target_dst_ip: Optional[str],
    verbose: bool,
) -> str:
    """Normalize a non-empty per-group joint subspec (same path as line-level)."""
    if not is_nonempty_subspec(subspec):
        return subspec

    metadata_type = "joint"
    try:
        util_file.save_synthesis_metadata(
            host, safe_name, str(compute_smt2_path), intermediate_dir, metadata_type
        )
        metadata_file = util_file.find_metadata_file(
            safe_name, host, metadata_type, intermediate_dir
        )
        if not metadata_file:
            raise FileNotFoundError(
                f"Joint metadata was not generated for slice {host}, "
                f"group {safe_name}"
            )

        core, suffix = strip_subspec_suffixes(subspec)
        # Pass this group's Config_* only — joint metadata may list other locations'
        # commented equalities (e.g. enable=false), which must not replace this group.
        normalized = normalize_subspec(
            core,
            metadata_file,
            safe_name,
            is_field_level=False,
            is_pair=False,
            target_dst_ip=target_dst_ip,
            max_iterations=util_keyword.SUBSPEC_NORM_COUNT,
            verbose=verbose,
            temp_dir=intermediate_dir,
            config_names=set(group_config_names),
        )
        normalized = normalized + suffix
        logger.info(
            "  Slice %s group %s: normalized joint subspec: %s",
            host,
            safe_name,
            normalized,
        )
        return normalized
    except Exception as exc:
        raise RuntimeError(
            f"Failed to normalize joint subspec for slice {host}, "
            f"group {safe_name}: {exc}"
        ) from exc


def _slice_check_paths(work_dir: Path, host: str) -> Tuple[Path, Path]:
    check_dir = work_dir / util_keyword.CONSISTENCY_CHECK_DIR
    violation_path = check_dir / util_file.violation_check_file_name(host)
    satisfaction_path = check_dir / util_file.satisfaction_check_file_name(host)
    if not violation_path.is_file():
        raise FileNotFoundError(
            f"Violation check not found for slice {host}: {violation_path}"
        )
    if not satisfaction_path.is_file():
        raise FileNotFoundError(
            f"Satisfaction check not found for slice {host}: {satisfaction_path}"
        )
    return violation_path, satisfaction_path


def _write_joint_simplification_query(
    satisfaction_path: Path,
    config_vars: Sequence[ConfigLocationVar],
    intermediate_dir: Path,
    host: str,
) -> Path:
    temp_path = Path(
        comment_out_config_vars_to_temp(
            satisfaction_path, config_vars, comment=True
        )
    )
    try:
        content = replace_check_sat_with_simplify(
            util_file.load_text(temp_path)
        )
    finally:
        util_file.delete_file(temp_path)

    output_path = (
        intermediate_dir
        / f"compute_joint_subspec_from_{host}_joint_all.smt2"
    )
    util_file.write_text(output_path, content)
    logger.info("    Compute joint subspec file saved to: %s", output_path)
    return output_path


def _groups_from_joint_goal(
    z3_output: str,
    host: str,
    config_vars: Sequence[ConfigLocationVar],
    compute_path: Path,
    intermediate_dir: Path,
    *,
    target_dst_ip: Optional[str],
    verbose: bool,
) -> List[JointGroupResult]:
    names = [config_var.name for config_var in config_vars]
    variables_by_name = {config_var.name: config_var for config_var in config_vars}
    partitions = partition_configs_by_z3_goal_connectivity(z3_output, names)
    logger.info(
        "  Slice %s: goal connectivity partitions (%d): %s",
        host,
        len(partitions),
        "; ".join("{" + ", ".join(group) + "}" for group in partitions),
    )

    groups: List[JointGroupResult] = []
    for index, group_names in enumerate(partitions):
        group_vars = [variables_by_name[name] for name in group_names]
        safe_name = _group_safe_name(group_names, index)
        extracted = extract_config_constraints_from_z3_goal(
            z3_output, set(group_names)
        )
        subspec = _restore_propagated_equalities(extracted, group_vars)
        logger.info(
            "  Slice %s group %s (%s): pre-norm: %s",
            host,
            safe_name,
            ", ".join(group_names),
            subspec,
        )
        normalized = _normalize_joint_group_subspec(
            subspec,
            host,
            safe_name,
            compute_path,
            intermediate_dir,
            group_config_names=group_names,
            target_dst_ip=target_dst_ip,
            verbose=verbose,
        )
        groups.append(
            JointGroupResult(
                hosts=[host],
                config_names=list(group_names),
                subspec=normalized,
            )
        )
    return groups


def compute_slice_joint_subspec(
    work_dir: Path,
    host: str,
    config_vars: Sequence[ConfigLocationVar],
    intermediate_dir: Path,
    *,
    keep_intermediate: bool = False,
    target_dst_ip: Optional[str] = None,
    verbose: bool = False,
) -> List[JointGroupResult]:
    """Comment all config_vars on this slice; return CC-partitioned joint groups."""
    if not config_vars:
        return []

    violation_path, satisfaction_path = _slice_check_paths(work_dir, host)
    names = [v.name for v in config_vars]
    logger.info(
        "  Slice %s: joint locations (%d): %s",
        host,
        len(names),
        ", ".join(names),
    )

    has_impact = check_impact_forward(
        violation_path,
        config_vars,
        intermediate_dir,
        host,
        "joint_all",
        baseline_has_check_sat=True,
        write_mode=ImpactCheckWriteMode.TEMP_WITH_DEBUG,
        cleanup_after=not keep_intermediate,
    )
    if not has_impact:
        logger.info("  Slice %s: empty subspec (no impact)", host)
        return [
            JointGroupResult(hosts=[host], config_names=[n], subspec="empty")
            for n in names
        ]

    compute_path = _write_joint_simplification_query(
        satisfaction_path, config_vars, intermediate_dir, host
    )
    try:
        z3_output = _run_z3_simplify(compute_path, f"joint@{host}")
        return _groups_from_joint_goal(
            z3_output,
            host,
            config_vars,
            compute_path,
            intermediate_dir,
            target_dst_ip=target_dst_ip,
            verbose=verbose,
        )
    finally:
        if not keep_intermediate:
            util_file.delete_file(compute_path)


def merge_necessary_cross_slice_groups(
    per_slice: Sequence[SliceJointResult],
) -> List[JointGroupResult]:
    """AND groups only when the same inseparable multi-config set hits >= 2 slices.

    Singletons are never cross-AND'd. A multi-config set that appears on only one
    slice stays as that per-slice group (no extra merged entry).
    """
    by_key: Dict[frozenset, List[JointGroupResult]] = defaultdict(list)
    for slice_result in per_slice:
        for group in slice_result.groups:
            if not is_nonempty_subspec(group.subspec):
                continue
            if not group.is_multi_config:
                continue
            key = frozenset(group.config_names)
            by_key[key].append(group)

    merged: List[JointGroupResult] = []
    for key, groups in by_key.items():
        hosts = sorted({h for g in groups for h in g.hosts})
        if len(hosts) < 2:
            continue
        parts: List[str] = []
        seen: Set[str] = set()
        for group in groups:
            for part in subspec_string_to_list(group.subspec):
                if part not in seen:
                    seen.add(part)
                    parts.append(part)
        config_order = list(groups[0].config_names)
        for name in key:
            if name not in config_order:
                config_order.append(name)
        formula = " AND ".join(parts) if parts else "empty"
        merged.append(
            JointGroupResult(hosts=hosts, config_names=config_order, subspec=formula)
        )
        logger.info(
            "Necessary cross-slice merge for {%s} across %s",
            ", ".join(config_order),
            ", ".join(hosts),
        )
    return merged


_DOT_SEP = "." * 50
_DASH_SEP = "-" * 50


def _expand_groups_for_presentation(
    groups: Sequence[JointGroupResult],
) -> List[JointGroupResult]:
    """Expand empty groups into one presentation entry per location."""
    expanded: List[JointGroupResult] = []
    for group in groups:
        if is_nonempty_subspec(group.subspec):
            expanded.append(group)
            continue
        for name in group.config_names:
            expanded.append(
                JointGroupResult(
                    hosts=list(group.hosts),
                    config_names=[name],
                    subspec="empty",
                )
            )
    return expanded


def _format_section_entries(
    title: str,
    groups: Sequence[JointGroupResult],
) -> List[str]:
    """Format one titled section matching the UI layout.

    Singleton (empty or not)::

        Config_xxx
        Subspecs (1):
          1. empty|formula
        ..................................................   # if more entries follow

    Multi-config nonempty::

        Config_yyy1
        Config_yyy2
        ..................................................
        Subspecs (1):
          1. formula

    Section ends with ``--------------------------------------------------``.
    """
    lines: List[str] = [title]
    entries = _expand_groups_for_presentation(groups)
    if not entries:
        lines.append("(none)")
        lines.append(_DASH_SEP)
        lines.append("")
        return lines

    for idx, group in enumerate(entries):
        body = group.subspec if is_nonempty_subspec(group.subspec) else "empty"
        multi_nonempty = group.is_multi_config and is_nonempty_subspec(group.subspec)

        for name in group.config_names:
            lines.append(name)

        if multi_nonempty:
            lines.append(_DOT_SEP)
            lines.append("Subspecs (1):")
            lines.append(f"  1. {body}")
        else:
            lines.append("Subspecs (1):")
            lines.append(f"  1. {body}")

        if idx < len(entries) - 1:
            lines.append(_DOT_SEP)
        else:
            lines.append(_DASH_SEP)
            lines.append("")
    return lines


def _collect_final_summary_groups(
    result: JointMultiLocationResult,
) -> List[JointGroupResult]:
    """Final ``joint subspec:`` entries: empties + nonempty (merge preferred).

    Order: locations order for empties, then necessary merges, then remaining
    per-slice nonempty groups not covered by a merge.
    """
    empty_names = list(result.empty_configs)
    empty_set = set(empty_names)
    summary: List[JointGroupResult] = [
        JointGroupResult(hosts=[], config_names=[n], subspec="empty")
        for n in empty_names
    ]

    merged_keys: Set[frozenset] = set()
    for group in result.merged_groups:
        if not is_nonempty_subspec(group.subspec):
            continue
        summary.append(group)
        merged_keys.add(frozenset(group.config_names))

    for slice_result in result.per_slice:
        for group in slice_result.groups:
            if not is_nonempty_subspec(group.subspec):
                continue
            key = frozenset(group.config_names)
            if key in merged_keys and group.is_multi_config:
                continue
            if group.config_names and all(n in empty_set for n in group.config_names):
                continue
            summary.append(group)
    return summary


def format_joint_result(result: JointMultiLocationResult) -> str:
    """Format per-slice joints, then a final aggregated ``joint subspec:`` section."""
    lines: List[str] = []
    lines.append("Joint Subspecs")
    lines.append("==============")
    lines.append("")

    if not result.per_slice:
        lines.append("No slice contained any of the locations.")
        lines.append("")
        return "\n".join(lines)

    for slice_result in result.per_slice:
        title = f"joint subspec (slice {slice_result.host}):"
        groups = slice_result.groups
        if not groups:
            groups = [
                JointGroupResult(
                    hosts=[slice_result.host],
                    config_names=[v.name for v in slice_result.locations],
                    subspec="empty",
                )
            ]
        lines.extend(_format_section_entries(title, groups))

    lines.extend(
        _format_section_entries("joint subspec:", _collect_final_summary_groups(result))
    )
    return "\n".join(lines)


def save_joint_result(
    work_dir: Path,
    result: JointMultiLocationResult,
    *,
    output_dir_name: str = util_keyword.SUBSPEC_DIR,
) -> Path:
    """Write one joint-level subspec result."""
    out_dir = work_dir / output_dir_name
    util_file.ensure_directory(out_dir)
    out_path = out_dir / util_keyword.JOINT_LEVEL_SUBSPECS_FILE
    util_file.write_text(out_path, format_joint_result(result))
    logger.info("Joint multi-location subspecs saved to: %s", out_path)
    return out_path


def _resolve_config_vars(
    loc_names: Sequence[str],
    reverse_path: Path,
    forward_path: Path,
) -> List[ConfigLocationVar]:
    """Resolve configuration equalities from consistency-check encodings."""
    config_vars = resolve_config_vars_in_file(reverse_path, loc_names)
    if not config_vars:
        config_vars = resolve_config_vars_in_file(forward_path, loc_names)

    by_name: Dict[str, ConfigLocationVar] = {v.name: v for v in config_vars}
    missing = [name for name in loc_names if name not in by_name]
    if missing:
        raise ValueError(
            "Could not resolve configuration values from "
            f"{reverse_path} or {forward_path}: {', '.join(missing)}"
        )

    return [by_name[name] for name in loc_names]


def _compute_per_slice_joint(
    work_path: Path,
    host: str,
    loc_names: Sequence[str],
    intermediate_dir: Path,
    *,
    target_dst_ip: Optional[str],
    verbose: bool,
) -> SliceJointResult:
    """Resolve equalities and compute joint groups for one slice + location list."""
    reverse_path = (
        work_path
        / util_keyword.CONSISTENCY_CHECK_DIR
        / util_file.violation_check_file_name(host)
    )
    forward_path = (
        work_path
        / util_keyword.CONSISTENCY_CHECK_DIR
        / util_file.satisfaction_check_file_name(host)
    )
    config_vars = _resolve_config_vars(loc_names, reverse_path, forward_path)
    groups = compute_slice_joint_subspec(
        work_path,
        host,
        config_vars,
        intermediate_dir,
        keep_intermediate=verbose,
        target_dst_ip=target_dst_ip,
        verbose=verbose,
    )
    return SliceJointResult(host=host, locations=list(config_vars), groups=groups)


@contextmanager
def _joint_intermediate_directory(
    work_dir: Path,
    directory_name: str,
    *,
    verbose: bool,
) -> Iterator[Path]:
    persistent_dir = work_dir / directory_name
    util_file.ensure_directory(persistent_dir)
    if verbose:
        yield persistent_dir
        return

    with util_file.create_temporary_directory(
        prefix="joint_subspec_"
    ) as temp_dir:
        yield Path(temp_dir)


def _compute_joint_slices(
    work_dir: Path,
    host_locations: Sequence[Tuple[str, Sequence[str]]],
    intermediate_dir: Path,
    *,
    target_dst_ip: Optional[str],
    verbose: bool,
) -> List[SliceJointResult]:
    slices: List[SliceJointResult] = []
    for host, location_names in host_locations:
        if not location_names:
            logger.info("Slice %s: no matching locations, skip", host)
            continue
        slices.append(
            _compute_per_slice_joint(
                work_dir,
                host,
                location_names,
                intermediate_dir,
                target_dst_ip=target_dst_ip,
                verbose=verbose,
            )
        )
    return slices


def _finalize_joint_result(
    work_dir: Path,
    result: JointMultiLocationResult,
    *,
    output_dir_name: str,
) -> Path:
    result.empty_configs = collect_empty_configs(
        result.locations, result.per_slice
    )
    result.merged_groups = merge_necessary_cross_slice_groups(
        result.per_slice
    )
    return save_joint_result(
        work_dir, result, output_dir_name=output_dir_name
    )


def _print_joint_summary(
    result: JointMultiLocationResult,
    output_path: Path,
) -> None:
    group_count = sum(len(slice_result.groups) for slice_result in result.per_slice)
    print(
        f"joint multi-location: {len(result.locations)} locations, "
        f"{len(result.per_slice)} slices hit"
    )
    print(
        f"  empty slices: {len(result.empty_slices)}; "
        f"non-empty slices: {len(result.nonempty_slices)}; "
        f"groups: {group_count}; empty Config: {len(result.empty_configs)}"
    )
    print(f"  necessary merged groups: {len(result.merged_groups)}")
    print(f"  saved: {output_path}")


def run_joint_multi_location_subspec(
    work_dir: str | Path,
    *,
    verbose: bool = False,
    device_filter: Optional[str] = None,
    intermediate_dir_name: str = util_file.intermediate_directory_name(
        4, util_keyword.INTERMEDIATE_JOINT_DIR_SUFFIX
    ),
    output_dir_name: str = util_keyword.SUBSPEC_DIR,
) -> JointMultiLocationResult:
    """Compute joint subspecs for ``0_multiple_locations.txt``."""
    work_path = Path(work_dir)
    locations = load_multiple_locations(work_path)
    hosts = list_ag_slice_hosts(work_path, device_filter=device_filter)
    result = JointMultiLocationResult(locations=locations)
    host_locations = [
        (host, locations_in_slice(locations, work_path, host))
        for host in hosts
    ]

    logger.info(
        "Starting joint multi-location subspec for %d locations",
        len(locations),
    )
    with _joint_intermediate_directory(
        work_path, intermediate_dir_name, verbose=verbose
    ) as intermediate_dir:
        result.per_slice = _compute_joint_slices(
            work_path,
            host_locations,
            intermediate_dir,
            target_dst_ip=util_file.load_target_dst_ip(work_path),
            verbose=verbose,
        )
        output_path = _finalize_joint_result(
            work_path, result, output_dir_name=output_dir_name
        )

    _print_joint_summary(result, output_path)
    return result
