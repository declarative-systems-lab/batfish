#!/usr/bin/env python3
"""Delete all output and intermediate directories from the work directory."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STAGE_SCRIPTS = (
    "1_router_level_subspec.py",
    "2_router_local_encoding.py",
    "3_consistency_checker.py",
    "4_subspec_simplifier.py",
    "5_subspec_simplifier_noscope.py",
    "6_subspec_simplifier_fullsym.py",
)
INTERMEDIATE_DIRECTORY_PATTERNS = (
    "4_intermediate_subspec_*",
    "5_intermediate_subspec_*",
    "6_intermediate_subspec_*",
)
TIMING_FILE_PATTERN = "times_*.txt"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Delete all Stage 1-6 output and intermediate directories "
            "from one work directory."
        )
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="Work directory whose generated outputs should be deleted",
    )
    return parser.parse_args(argv)


def validate_inputs(work_directory: Path) -> list[Path]:
    if not work_directory.is_dir():
        raise NotADirectoryError(
            f"Work directory not found: {work_directory}"
        )

    scripts = [PROJECT_ROOT / script_name for script_name in STAGE_SCRIPTS]
    missing_scripts = [script for script in scripts if not script.is_file()]
    if missing_scripts:
        missing = ", ".join(str(script) for script in missing_scripts)
        raise FileNotFoundError(f"Stage scripts not found: {missing}")
    return scripts


def clean_intermediate_directories(work_directory: Path) -> None:
    """Remove current and legacy Stage 4-6 intermediate directories."""
    for pattern in INTERMEDIATE_DIRECTORY_PATTERNS:
        for directory in sorted(work_directory.glob(pattern)):
            if directory.is_dir():
                shutil.rmtree(directory)


def clean_timing_files(work_directory: Path) -> None:
    """Remove timing reports produced by the pipeline runner."""
    for timing_file in sorted(work_directory.glob(TIMING_FILE_PATTERN)):
        if timing_file.is_file():
            timing_file.unlink()


def clean_stage(script: Path, work_directory: Path) -> None:
    command = [
        sys.executable,
        str(script),
        "-d",
        str(work_directory.resolve()),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return

    diagnostic = (result.stderr or result.stdout).strip()
    message = f"Failed to clean outputs with {script.name}"
    if diagnostic:
        message += f":\n{diagnostic}"
    raise RuntimeError(message)


def clean_work_directory(work_directory: Path) -> None:
    """Delete generated outputs directly under one work directory."""
    failures = []
    for script in validate_inputs(work_directory):
        try:
            clean_stage(script, work_directory)
        except RuntimeError as exc:
            failures.append(str(exc))
    clean_intermediate_directories(work_directory)
    clean_timing_files(work_directory)
    if failures:
        raise RuntimeError("\n".join(failures))


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        clean_work_directory(options.work_directory)
    except (FileNotFoundError, NotADirectoryError, RuntimeError) as exc:
        print(f"[✗] Failed: {exc}", file=sys.stderr)
        return 1

    print(
        "[✓] Completed: Cleaned Work Directory "
        f"{options.work_directory.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
