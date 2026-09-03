#!/usr/bin/env python3
"""Count non-empty and total entries in one case's standard SubSpec output."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence


SUBSPEC_DIRECTORY = "4_subspec"
SUBSPEC_COUNT_RE = re.compile(r"Subspecs\s*\((\d+)\)\s*:?")
SUBSPEC_LINE_RE = re.compile(r"^\s*\d+\.\s+(.+)$")
SEPARATOR_RE = re.compile(r"^-{50}$")
NO_SUBSPECS_FOUND_LINE = "No subspecs found."

EntryOutcome = Literal["non_empty", "empty", "not_found"]
OUTCOME_PRIORITY: dict[EntryOutcome, int] = {
    "non_empty": 3,
    "empty": 2,
    "not_found": 1,
}


@dataclass(frozen=True)
class LevelCounts:
    """Coverage counts for one SubSpec level."""

    non_empty: int
    total: int


@dataclass(frozen=True)
class SubspecCounts:
    """Field- and line-level coverage counts for one SMT case."""

    field: LevelCounts
    line: LevelCounts


def _classify_entry(
    subspecs: list[str],
    no_subspecs_found: bool,
) -> EntryOutcome | None:
    if any(subspec.strip() != "empty" for subspec in subspecs):
        return "non_empty"
    if no_subspecs_found:
        return "not_found"
    if subspecs:
        return "empty"
    return None


def _merge_outcome(
    existing: EntryOutcome | None,
    new: EntryOutcome,
) -> EntryOutcome:
    if existing is None or OUTCOME_PRIORITY[new] > OUTCOME_PRIORITY[existing]:
        return new
    return existing


def _parse_subspec_file(
    file_path: Path,
    entry_label: str,
) -> dict[str, EntryOutcome]:
    outcomes: dict[str, EntryOutcome] = {}
    current_name: str | None = None
    subspecs: list[str] = []
    no_subspecs_found = False

    def finish_entry() -> None:
        nonlocal current_name, subspecs, no_subspecs_found
        if current_name is not None:
            outcome = _classify_entry(subspecs, no_subspecs_found)
            if outcome is not None:
                outcomes[current_name] = _merge_outcome(
                    outcomes.get(current_name), outcome
                )
        current_name = None
        subspecs = []
        no_subspecs_found = False

    lines = file_path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        index += 1

        if stripped.startswith(entry_label):
            finish_entry()
            current_name = stripped[len(entry_label) :].strip()
            continue

        if stripped == NO_SUBSPECS_FOUND_LINE and current_name is not None:
            no_subspecs_found = True
            continue

        match = SUBSPEC_COUNT_RE.match(stripped)
        if match and current_name is not None:
            subspecs = []
            no_subspecs_found = False
            for _ in range(int(match.group(1))):
                if index >= len(lines):
                    break
                subspec_line = SUBSPEC_LINE_RE.match(lines[index].strip())
                index += 1
                if subspec_line:
                    subspecs.append(subspec_line.group(1).strip())
            continue

        if SEPARATOR_RE.match(stripped):
            finish_entry()

    finish_entry()
    return outcomes


def _count_level(
    directory: Path,
    pattern: str,
    entry_label: str,
) -> LevelCounts:
    outcomes: dict[str, EntryOutcome] = {}
    for file_path in sorted(directory.glob(pattern)):
        for name, outcome in _parse_subspec_file(file_path, entry_label).items():
            outcomes[name] = _merge_outcome(outcomes.get(name), outcome)
    return LevelCounts(
        non_empty=sum(outcome == "non_empty" for outcome in outcomes.values()),
        total=len(outcomes),
    )


def count_subspec_dir(subspec_directory: Path) -> SubspecCounts:
    """Count a `4_subspec` directory, merging per-device output files."""
    if not subspec_directory.is_dir():
        raise FileNotFoundError(f"SubSpec directory not found: {subspec_directory}")
    return SubspecCounts(
        field=_count_level(
            subspec_directory,
            "field_level_subspecs*.txt",
            "Config Variable:",
        ),
        line=_count_level(
            subspec_directory,
            "line_level_subspecs*.txt",
            "Line Group:",
        ),
    )


def count_subspecs(work_directory: Path) -> SubspecCounts:
    """Count standard SubSpecs produced for one SMT case."""
    return count_subspec_dir(work_directory / SUBSPEC_DIRECTORY)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Count standard SubSpecs for one SMT case."
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="SMT case directory containing 4_subspec/",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        counts = count_subspecs(options.work_directory.resolve())
    except FileNotFoundError as error:
        print(f"Error: {error}")
        return 1

    print(f"field_non_empty={counts.field.non_empty}")
    print(f"field_all={counts.field.total}")
    print(f"line_non_empty={counts.line.non_empty}")
    print(f"line_all={counts.line.total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
