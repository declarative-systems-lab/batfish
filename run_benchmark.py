#!/usr/bin/env python3
"""Run the benchmark pipeline for every property in a work directory."""

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

from speclens.tools.progress import TerminalSpinner


ROOT_DIRECTORY = Path(__file__).resolve().parent
SPECLENS_RUNNER = ROOT_DIRECTORY / "speclens" / "tools" / "run.py"
BAZEL_TARGET = "//projects/allinone:smt_property_tests"
BAZEL_TEST_TIMEOUT_SECONDS = 3000
DEFAULT_THREADS = 1
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60
PIPELINE_SEPARATOR = "-" * 70

OUTPUT_DIRECTORY_PATTERN = re.compile(
    r"^Output Directory: (smt_output_\d+)$"
)
BATFISH_SIMULATION_TIME_PATTERN = re.compile(
    r"^SPECLENS_BATFISH_SIMULATION_MS=(\d+)$"
)
CONFIGURATION_ENCODING_TIME_PATTERN = re.compile(
    r"^SPECLENS_CONFIGURATION_ENCODING_MS=(\d+)$"
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


def _duration_seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        match = re.fullmatch(
            r"(?:(\d+(?:\.\d+)?)h)?"
            r"(?:(\d+(?:\.\d+)?)m)?"
            r"(?:(\d+(?:\.\d+)?)s)?",
            value,
        )
        if match is None or not any(match.groups()):
            raise argparse.ArgumentTypeError(
                "expected seconds or a duration such as 4h3m2s, "
                f"got {value!r}"
            )
        hours, minutes, seconds = (
            float(part or 0) for part in match.groups()
        )
        number = hours * 3600 + minutes * 60 + seconds
    if number <= 0:
        raise argparse.ArgumentTypeError(
            f"expected a positive duration, got {value!r}"
        )
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        add_help=False,
        usage=(
            "%(prog)s [--subspec | --noscope | --fullsym | --all] [-c] "
            "[--property INDEX] [--benchmark NAME] [--threads THREADS] "
            "[--timeout DURATION] [--internet2] [-v] "
            "work_directory [-h]"
        ),
        description=(
            "Generate one SMT output per property and run SpecLens on it."
        ),
        epilog=(
            "The full-symbolic baseline is generated automatically from "
            "the verification property."
        ),
    )
    workflows = parser.add_argument_group("SpecLens workflows")
    workflow = workflows.add_mutually_exclusive_group()
    workflow.add_argument(
        "--subspec",
        action="store_true",
        help="run the standard subspecification workflow (default)",
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
    workflow.add_argument(
        "--all",
        action="store_true",
        help="run all subspecification workflows",
    )
    parser.add_argument(
        "-c",
        "--community",
        action="store_true",
        help="enable community subspecification",
    )
    parser.add_argument(
        "--property",
        type=_positive_int,
        default=None,
        metavar="INDEX",
        help="run only one 1-based property index",
    )
    parser.add_argument(
        "--benchmark",
        default=None,
        metavar="NAME",
        help="benchmark label stored in benchmark_time.csv",
    )
    parser.add_argument(
        "--threads",
        type=_positive_int,
        default=None,
        help="override the SpecLens concurrent device task limit",
    )
    parser.add_argument(
        "--timeout",
        type=_duration_seconds,
        default=None,
        metavar="DURATION",
        help=(
            "override the timeout for each property's SpecLens workflow "
            "(for example: 7200, 2h, or 1h30m)"
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
    options = parser.parse_args(argv)
    if not (
        options.subspec
        or options.noscope
        or options.fullsym
        or options.all
    ):
        options.subspec = True
    return options


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _display_path(path: Path) -> str:
    """Return a concise path relative to the repository root."""
    return os.path.relpath(path, ROOT_DIRECTORY)


def _format_duration(seconds: float) -> str:
    hours, remaining = divmod(seconds, 60 * 60)
    minutes, remaining = divmod(remaining, 60)
    parts = []
    if hours:
        parts.append(f"{int(hours)}h")
    if minutes:
        parts.append(f"{int(minutes)}min")
    if remaining or not parts:
        parts.append(f"{remaining:g}s")
    return " ".join(parts)


def _workflow_name(options: argparse.Namespace) -> str:
    if options.all:
        return "all (SubSpec + NoScope + FullSym)"
    if options.noscope:
        return "NoScope"
    if options.fullsym:
        return "FullSym"
    return "SubSpec"


def _report_run_options(options: argparse.Namespace) -> None:
    threads = options.threads or DEFAULT_THREADS
    timeout = options.timeout or DEFAULT_TIMEOUT_SECONDS
    print(f"[!] Note: Parallel threads: {threads}")
    print(f"[!] Note: Timeout: {_format_duration(timeout)}")
    if options.property is not None:
        print(f"[!] Note: Property: {options.property}")
    print(f"[!] Note: Workflow: {_workflow_name(options)}")
    print(
        "[!] Note: Community subspec extension: "
        f"{str(options.community).lower()}"
    )
    print(
        "[!] Note: Internet2 refinement: "
        f"{str(options.internet2).lower()}"
    )
    print(PIPELINE_SEPARATOR)


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


def run_visible_command(command: Sequence[str]) -> CommandResult:
    """Run a command with direct terminal access for interactive progress."""
    result = subprocess.run(
        list(command),
        cwd=ROOT_DIRECTORY,
        check=False,
    )
    return CommandResult(result.returncode, "")


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
    with TerminalSpinner("Running: Build Projects", enabled=not verbose):
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
        f"--sandbox_writable_path={output_root}",
        f"--test_env=SMT_WORK_DIRECTORY={relative_work_directory}",
        f"--test_env=SMT_DIRECTORY_PREFIX={output_root}",
        f"--test_env=SMT_PROPERTY_INDEX={property_index}",
    )
    description = (
        f"Running: Property {property_index:02d} "
        "(Simulation State & Verification Encoding)"
    )
    with TerminalSpinner(description, enabled=not verbose):
        result = run_command(
            command,
            verbose=verbose,
        )
    if not result.succeeded:
        return None, result

    directory_matches = [
        OUTPUT_DIRECTORY_PATTERN.fullmatch(line.strip())
        for line in result.output.splitlines()
    ]
    directory_matches = [
        match for match in directory_matches if match is not None
    ]
    if len(directory_matches) != 1:
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


def parse_step1_time(output: str) -> float:
    """Return Batfish simulation plus configuration encoding time in seconds."""
    simulation_times = []
    encoding_times = []
    for line in output.splitlines():
        line = line.strip()
        simulation_match = BATFISH_SIMULATION_TIME_PATTERN.fullmatch(line)
        if simulation_match is not None:
            simulation_times.append(int(simulation_match.group(1)))
        encoding_match = CONFIGURATION_ENCODING_TIME_PATTERN.fullmatch(line)
        if encoding_match is not None:
            encoding_times.append(int(encoding_match.group(1)))
    if len(simulation_times) != 1 or not encoding_times:
        raise ValueError(
            "Unable to identify Batfish simulation and configuration "
            "encoding timings from benchmark output"
        )
    return (simulation_times[0] + sum(encoding_times)) / 1000.0


def run_speclens(
    output_directory: Path,
    options: argparse.Namespace,
    *,
    benchmark: str,
    step1_time: float,
) -> CommandResult:
    command = [sys.executable, "-u", str(SPECLENS_RUNNER)]
    if options.subspec:
        command.append("--subspec")
    if options.noscope:
        command.append("--noscope")
    if options.fullsym:
        command.append("--fullsym")
    if options.all:
        command.append("--all")
    if options.community:
        command.append("--community")
    command.extend(
        ("--threads", str(options.threads or DEFAULT_THREADS))
    )
    if options.timeout is not None:
        command.extend(("--timeout", str(options.timeout)))
    if options.internet2:
        command.append("--internet2")
    if options.verbose:
        command.append("--verbose")
    command.extend(("--benchmark", benchmark))
    command.extend(("--step1-time", str(step1_time)))
    command.append(str(output_directory))
    return run_visible_command(command)


def run_pipeline(options: argparse.Namespace) -> bool:
    _report_run_options(options)
    if not SPECLENS_RUNNER.is_file():
        raise FileNotFoundError(f"SpecLens runner not found: {SPECLENS_RUNNER}")
    if not build_projects(options.verbose):
        return False

    with TerminalSpinner(
        "Running: Load Configurations",
        enabled=not options.verbose,
    ):
        work_directory, property_count = validate_work_directory(
            options.work_directory
        )
    print(
        "[✓] Completed: Load Configurations from "
        f"'{work_directory.relative_to(ROOT_DIRECTORY)}'"
    )
    output_root = _output_root()
    if options.property is not None:
        if options.property > property_count:
            raise ValueError(
                f"Property index {options.property} exceeds the "
                f"{property_count} properties in {work_directory}"
            )
        property_indexes = (options.property,)
    else:
        property_indexes = range(1, property_count + 1)

    all_succeeded = True
    for property_index in property_indexes:
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
            all_succeeded = False
            continue

        print(
            f"[✓] Completed: Property {property_index:02d} "
            "(Simulation State & Verification Encoding)"
        )
        try:
            step1_time = parse_step1_time(generation_result.output)
        except ValueError as error:
            print(f"[✗] Failed: {error}", file=sys.stderr)
            all_succeeded = False
            continue
        output_display_path = _display_path(output_directory)
        with TerminalSpinner(
            f"Running: Store Outputs to '{output_display_path}'",
            enabled=not options.verbose,
        ):
            if not output_directory.is_dir():
                raise FileNotFoundError(
                    f"Generated SMT output not found: {output_directory}"
                )
        print(f"[✓] Completed: Store Outputs to '{output_display_path}'")
        print(PIPELINE_SEPARATOR)
        speclens_result = run_speclens(
            output_directory,
            options,
            benchmark=options.benchmark or work_directory.name.lower(),
            step1_time=step1_time,
        )
        if not speclens_result.succeeded:
            report_failure(
                f"Property {property_index:02d} SpecLens Pipeline",
                speclens_result,
                output_already_visible=True,
            )
            all_succeeded = False

    return all_succeeded


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
