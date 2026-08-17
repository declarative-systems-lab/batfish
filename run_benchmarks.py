#!/usr/bin/env python3
"""Generate and analyze one SMT output per benchmark property."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ROOT_DIRECTORY = Path(__file__).resolve().parent
SPECLENS_RUNNER = ROOT_DIRECTORY / "speclens" / "tools" / "run.py"
BAZEL_TARGET = "//projects/allinone:smt_property_tests"
DEFAULT_THREADS = 20
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60
BAZEL_TEST_TIMEOUT_SECONDS = 3000
PIPELINE_SEPARATOR = "-" * 70

PROPERTY_STATUS_PATTERN = re.compile(
    r"^\[✓\] Completed: Property (\d+) "
    r"\(Simulation State & Verification Encoding\)$"
)
OUTPUT_DIRECTORY_PATTERN = re.compile(
    r"^Output Directory: (smt_output_\d+)$"
)


@dataclass(frozen=True)
class CommandResult:
    """Captured result of one external command."""

    returncode: int
    output: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}"
        ) from error
    if number <= 0:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, got {value!r}"
        )
    return number


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a positive number, got {value!r}"
        ) from error
    if number <= 0:
        raise argparse.ArgumentTypeError(
            f"expected a positive number, got {value!r}"
        )
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        add_help=False,
        usage=(
            "%(prog)s (--subspec | --noscope | --fullsym) [-c] "
            "[-t THREADS] [--timeout SECONDS] [--internet2] [-v] "
            "work_directory [-h]"
        ),
        description=(
            "Generate one SMT output per property and run SpecLens on it."
        ),
        epilog=(
            "The full-symbolic workflow requires a manually prepared "
            "2_router_local_encoding/global_encoding_subspec.smt2."
        ),
    )
    workflows = parser.add_argument_group("SpecLens workflows")
    workflow = workflows.add_mutually_exclusive_group(required=True)
    workflow.add_argument(
        "--subspec",
        action="store_true",
        help="run the standard subspecification workflow",
    )
    workflow.add_argument(
        "--noscope",
        action="store_true",
        help="run the no-scope subspecification workflow",
    )
    workflow.add_argument(
        "--fullsym",
        action="store_true",
        help="run the fully symbolic subspecification workflow",
    )
    parser.add_argument(
        "-c",
        "--community",
        action="store_true",
        help="enable community subspecification",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=_positive_int,
        default=DEFAULT_THREADS,
        help=f"maximum SpecLens device workers (default: {DEFAULT_THREADS})",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=(
            "timeout for each property's SpecLens workflow "
            f"(default: {DEFAULT_TIMEOUT_SECONDS} seconds)"
        ),
    )
    parser.add_argument(
        "--internet2",
        action="store_true",
        help="enable Internet2 consistency refinement",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show complete Bazel and detailed SpecLens stage output",
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="directory under benchmarks/ or user-study/",
    )
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help="show this help message and exit",
    )
    return parser.parse_args(argv)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _display_path(path: Path) -> str:
    """Return a concise path relative to the repository root."""
    return os.path.relpath(path, ROOT_DIRECTORY)


def validate_work_directory(work_directory: Path) -> tuple[Path, int]:
    resolved_directory = work_directory.resolve()
    input_roots = (
        ROOT_DIRECTORY / "benchmarks",
        ROOT_DIRECTORY / "user-study",
    )
    if not resolved_directory.is_dir():
        raise NotADirectoryError(
            f"Work directory not found: {resolved_directory}"
        )
    if not any(
        _is_relative_to(resolved_directory, root.resolve())
        for root in input_roots
    ):
        raise ValueError(
            "Work directory must be below benchmarks/ or user-study/"
        )
    if not (resolved_directory / "configs").is_dir():
        raise FileNotFoundError(
            f"Configs directory not found: {resolved_directory / 'configs'}"
        )

    properties_file = resolved_directory / "properties.json"
    if not properties_file.is_file():
        raise FileNotFoundError(
            f"Property specification not found: {properties_file}"
        )
    try:
        root = json.loads(properties_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Invalid property specification {properties_file}: {error}"
        ) from error
    properties = root.get("properties") if isinstance(root, dict) else None
    if not isinstance(properties, list) or not properties:
        raise ValueError(
            f"{properties_file} must contain a non-empty properties array"
        )
    if any(not isinstance(property_spec, dict) for property_spec in properties):
        raise ValueError(
            f"Every entry in {properties_file} must be a JSON object"
        )
    return resolved_directory, len(properties)


def run_command(
    command: Sequence[str],
    *,
    verbose: bool,
    visible_prefixes: tuple[str, ...] = (),
) -> CommandResult:
    """Run a command while capturing diagnostics and selected status lines."""
    process = subprocess.Popen(
        list(command),
        cwd=ROOT_DIRECTORY,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    assert process.stdout is not None
    for line in process.stdout:
        output_lines.append(line)
        if verbose or line.startswith(visible_prefixes):
            print(line, end="")
    return CommandResult(process.wait(), "".join(output_lines))


def report_failure(
    description: str,
    result: CommandResult,
    *,
    output_already_visible: bool = False,
) -> None:
    print(f"[✗] Failed: {description}", file=sys.stderr)
    if not output_already_visible and result.output.strip():
        print(result.output.rstrip(), file=sys.stderr)


def build_projects(verbose: bool) -> bool:
    result = run_command(
        ("bazelisk", "build", BAZEL_TARGET),
        verbose=verbose,
    )
    if not result.succeeded:
        report_failure(
            "Build Projects",
            result,
            output_already_visible=verbose,
        )
        return False
    print("[✓] Completed: Build Projects")
    return True


def _output_root() -> Path:
    configured_root = os.environ.get("SMT_DIRECTORY_PREFIX")
    output_root = (
        Path(configured_root)
        if configured_root is not None
        else ROOT_DIRECTORY / "smts"
    )
    if not output_root.is_absolute():
        output_root = ROOT_DIRECTORY / output_root
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root.resolve()


def generate_property(
    work_directory: Path,
    property_index: int,
    *,
    output_root: Path,
    verbose: bool,
) -> tuple[Path | None, CommandResult]:
    relative_work_directory = work_directory.relative_to(ROOT_DIRECTORY)
    command = (
        "bazelisk",
        "test",
        BAZEL_TARGET,
        "--test_filter=org.batfish.allinone.smt.SmtPropertyTest#testProperty",
        "--cache_test_results=no",
        f"--test_timeout={BAZEL_TEST_TIMEOUT_SECONDS}",
        "--test_output=streamed",
        f"--test_env=SMT_WORK_DIRECTORY={relative_work_directory}",
        f"--test_env=SMT_DIRECTORY_PREFIX={output_root}",
        f"--test_env=SMT_PROPERTY_INDEX={property_index}",
    )
    result = run_command(
        command,
        verbose=verbose,
        visible_prefixes=(
            "[✓] Completed: Property ",
            "[✗] Failed: Property ",
        ),
    )
    if not result.succeeded:
        return None, result

    property_matches = [
        PROPERTY_STATUS_PATTERN.fullmatch(line.strip())
        for line in result.output.splitlines()
    ]
    property_matches = [
        match for match in property_matches if match is not None
    ]
    directory_matches = [
        OUTPUT_DIRECTORY_PATTERN.fullmatch(line.strip())
        for line in result.output.splitlines()
    ]
    directory_matches = [
        match for match in directory_matches if match is not None
    ]
    if (
        len(property_matches) != 1
        or int(property_matches[0].group(1)) != property_index
        or len(directory_matches) != 1
    ):
        return None, CommandResult(
            1,
            result.output
            + "\nUnable to identify the generated SMT output directory.\n",
        )

    output_directory = output_root / directory_matches[0].group(1)
    if not output_directory.is_dir():
        return None, CommandResult(
            1,
            result.output
            + f"\nGenerated SMT output not found: {output_directory}\n",
        )
    return output_directory, result


def run_speclens(
    output_directory: Path,
    options: argparse.Namespace,
) -> CommandResult:
    command = [sys.executable, str(SPECLENS_RUNNER)]
    if options.subspec:
        command.append("--subspec")
    if options.noscope:
        command.append("--noscope")
    if options.fullsym:
        command.append("--fullsym")
    if options.community:
        command.append("--community")
    command.extend(("--threads", str(options.threads)))
    command.extend(("--timeout", str(options.timeout)))
    if options.internet2:
        command.append("--internet2")
    if options.verbose:
        command.append("--verbose")
    command.append(str(output_directory))
    return run_command(
        command,
        verbose=True,
    )


def run_pipeline(options: argparse.Namespace) -> bool:
    work_directory, property_count = validate_work_directory(
        options.work_directory
    )
    if not SPECLENS_RUNNER.is_file():
        raise FileNotFoundError(f"SpecLens runner not found: {SPECLENS_RUNNER}")
    if not build_projects(options.verbose):
        return False

    print(
        "[✓] Completed: Load Configurations from "
        f"'{work_directory.relative_to(ROOT_DIRECTORY)}'"
    )
    output_root = _output_root()
    for property_index in range(1, property_count + 1):
        print()
        output_directory, generation_result = generate_property(
            work_directory,
            property_index,
            output_root=output_root,
            verbose=options.verbose,
        )
        if output_directory is None:
            report_failure(
                f"Property {property_index:02d} Benchmark Generation",
                generation_result,
                output_already_visible=options.verbose,
            )
            return False

        print(
            "[✓] Completed: Store Outputs to "
            f"'{_display_path(output_directory)}'"
        )
        print(PIPELINE_SEPARATOR)
        speclens_result = run_speclens(output_directory, options)
        if not speclens_result.succeeded:
            report_failure(
                f"Property {property_index:02d} SpecLens Pipeline",
                speclens_result,
                output_already_visible=True,
            )
            return False

    return True


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        return 0 if run_pipeline(options) else 1
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as error:
        print(f"[✗] Failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[✗] Failed: Benchmark Pipeline Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
