#!/usr/bin/env python3
"""Run the SpecLens pipeline for one work directory."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils import util_file, util_keyword  # noqa: E402


DEFAULT_THREADS = 20
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60
PROCESS_TERMINATION_GRACE_SECONDS = 5
TIMING_FILE_PATTERN = re.compile(r"times_(\d{4})\.txt")


@dataclass(frozen=True)
class Step:
    """One serial or per-device pipeline operation."""

    name: str
    description: str
    script: str
    arguments: tuple[str, ...] = ()
    per_device: bool = False


@dataclass(frozen=True)
class CommandResult:
    """Result of one external command."""

    returncode: Optional[int]
    elapsed_seconds: float
    output: str
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.returncode == 0


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
        description="Run the SpecLens pipeline for one work directory.",
        epilog=(
            "At least one workflow selector is required. Stage 6 requires "
            "a manually prepared "
            "2_router_local_encoding/global_encoding_subspec.smt2."
        ),
    )
    stages = parser.add_argument_group("subspecification stages")
    stages.add_argument(
        "--subspec",
        action="store_true",
        help="run Stages 1, 2, 3, and 4",
    )
    stages.add_argument(
        "--noscope",
        action="store_true",
        help="run Stages 1, 2, 3, and 5",
    )
    stages.add_argument(
        "--fullsym",
        action="store_true",
        help="run Stages 2 and 6",
    )
    parser.add_argument(
        "-c",
        "--community",
        action="store_true",
        dest="community",
        help="enable community subspecification in selected stages",
    )
    parser.add_argument(
        "-t",
        "--threads",
        type=_positive_int,
        default=DEFAULT_THREADS,
        help=f"maximum concurrent device tasks (default: {DEFAULT_THREADS})",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=(
            "timeout for the entire selected workflow "
            f"(default: {DEFAULT_TIMEOUT_SECONDS} seconds)"
        ),
    )
    parser.add_argument(
        "--internet2",
        action="store_true",
        help="enable Internet2 refinement during the consistency check",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show detailed stage output and keep intermediate files",
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="work directory containing the SMT and simulation inputs",
    )
    options = parser.parse_args(argv)
    if not (options.subspec or options.noscope or options.fullsym):
        parser.error(
            "at least one of --subspec, --noscope, or --fullsym is required"
        )
    return options


def _selected_stages(options: argparse.Namespace) -> tuple[bool, bool, bool]:
    return options.subspec, options.noscope, options.fullsym


def build_steps(options: argparse.Namespace) -> list[Step]:
    """Build the ordered pipeline selected by the command line."""
    run_subspec, run_noscope, run_fullsym = _selected_stages(options)
    run_standard_pipeline = run_subspec or run_noscope
    verbose_argument = ("-v",) if options.verbose else ()
    steps = []
    if run_standard_pipeline:
        steps.append(
            Step(
                "router_level_subspec",
                "Router-Level Functional Subspecification",
                "1_router_level_subspec.py",
                verbose_argument,
            )
        )
    if run_standard_pipeline or run_fullsym:
        steps.append(
            Step(
                "router_local_encoding",
                "Router-Local Slice Encoding",
                "2_router_local_encoding.py",
                verbose_argument,
            )
        )
    if run_standard_pipeline:
        steps.append(
            Step(
                "consistency_check",
                "Consistency Check",
                "3_consistency_checker.py",
                (("--internet2",) if options.internet2 else ())
                + verbose_argument,
                per_device=True,
            )
        )

    community_argument = ("-c",) if options.community else ()
    if run_subspec:
        steps.extend(
            [
                Step(
                    "subspec_line",
                    "Line-Level Subspecification",
                    "4_subspec_simplifier.py",
                    ("-o", "-l") + community_argument + verbose_argument,
                    per_device=True,
                ),
                Step(
                    "subspec_field",
                    "Field-Level Subspecification",
                    "4_subspec_simplifier.py",
                    ("-o", "-f") + community_argument + verbose_argument,
                    per_device=True,
                ),
            ]
        )
    if run_noscope:
        steps.extend(
            [
                Step(
                    "noscope_line",
                    "No-Scope Line-Level Subspecification",
                    "5_subspec_simplifier_noscope.py",
                    ("-l",) + community_argument + verbose_argument,
                    per_device=True,
                ),
                Step(
                    "noscope_field",
                    "No-Scope Field-Level Subspecification",
                    "5_subspec_simplifier_noscope.py",
                    ("-f",) + community_argument + verbose_argument,
                    per_device=True,
                ),
            ]
        )
    if run_fullsym:
        steps.extend(
            [
                Step(
                    "fullsym_line",
                    "Fully Symbolic Line-Level Subspecification",
                    "6_subspec_simplifier_fullsym.py",
                    ("-l",) + community_argument + verbose_argument,
                    per_device=True,
                ),
                Step(
                    "fullsym_field",
                    "Fully Symbolic Field-Level Subspecification",
                    "6_subspec_simplifier_fullsym.py",
                    ("-f",) + community_argument + verbose_argument,
                    per_device=True,
                ),
            ]
        )
    return steps


def validate_inputs(work_directory: Path, steps: Sequence[Step]) -> None:
    if not work_directory.is_dir():
        raise NotADirectoryError(
            f"Work directory not found: {work_directory}"
        )

    missing_scripts = sorted(
        {
            str(PROJECT_ROOT / step.script)
            for step in steps
            if not (PROJECT_ROOT / step.script).is_file()
        }
    )
    if missing_scripts:
        raise FileNotFoundError(
            f"Stage scripts not found: {', '.join(missing_scripts)}"
        )


def validate_options(options: argparse.Namespace, work_directory: Path) -> None:
    run_subspec, run_noscope, run_fullsym = _selected_stages(options)
    if options.internet2 and not (run_subspec or run_noscope):
        raise ValueError(
            "--internet2 requires --subspec or --noscope because "
            "--fullsym does not run the consistency checker"
        )
    if not run_fullsym:
        return

    # Stage 6 needs a manually adjusted baseline that Stage 2 preserves.
    fullsym_baseline = (
        work_directory
        / util_keyword.ROUTER_LOCAL_ENCODING_DIR
        / util_keyword.GLOBAL_SUBSPEC_ENCODING_FILE
    )
    if not fullsym_baseline.is_file():
        source_baseline = (
            work_directory
            / util_keyword.ROUTER_LOCAL_ENCODING_DIR
            / util_keyword.GLOBAL_ENCODING_FILE
        )
        raise FileNotFoundError(
            f"Full-symbolic subspecification baseline not found: "
            f"{fullsym_baseline}. Create it by manually adjusting "
            f"{source_baseline}."
        )


def _terminate_process(process: subprocess.Popen[str]) -> None:
    """Terminate the command and its descendants, including Z3 processes."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def run_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
) -> CommandResult:
    """Run one command with a timeout and captured combined output."""
    started_at = time.monotonic()
    if timeout_seconds <= 0:
        return CommandResult(None, 0.0, "Timeout expired", timed_out=True)

    try:
        process = subprocess.Popen(
            list(command),
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
    except OSError as error:
        return CommandResult(
            None,
            time.monotonic() - started_at,
            f"Failed to start command: {error}",
        )

    try:
        output, _ = process.communicate(timeout=timeout_seconds)
        return CommandResult(
            process.returncode,
            time.monotonic() - started_at,
            output,
        )
    except subprocess.TimeoutExpired:
        _terminate_process(process)
        output, _ = process.communicate()
        return CommandResult(
            process.returncode,
            time.monotonic() - started_at,
            output,
            timed_out=True,
        )


def _step_command(
    step: Step,
    work_directory: Path,
    *,
    device: Optional[str] = None,
) -> list[str]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / step.script),
        *step.arguments,
    ]
    if device is not None:
        command.extend(("--device", device))
    command.append(str(work_directory))
    return command


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    if seconds < 3600:
        minutes, remaining = divmod(seconds, 60)
        return f"{int(minutes)}m {remaining:.2f}s"
    hours, remaining = divmod(seconds, 3600)
    minutes, remaining = divmod(remaining, 60)
    return f"{int(hours)}h {int(minutes)}m {remaining:.2f}s"


def _diagnostic(output: str, *, line_count: int = 5) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    return "\n".join(lines[-line_count:])


def _uncertain_status_lines(output: str) -> list[str]:
    """Extract refinable failures that a successful command must not hide."""
    return [
        line
        for line in output.splitlines()
        if line.startswith("[?] Failed:")
    ]


def _next_timing_file(work_directory: Path) -> Path:
    indexes = []
    for path in work_directory.glob("times_*.txt"):
        match = TIMING_FILE_PATTERN.fullmatch(path.name)
        if match:
            indexes.append(int(match.group(1)))
    next_index = max(indexes, default=0) + 1
    return work_directory / f"times_{next_index:04d}.txt"


class TimingReport:
    """Persist step timings as the pipeline progresses."""

    def __init__(self, path: Path, work_directory: Path) -> None:
        self.path = path
        self.path.write_text(
            f"started_at={datetime.now().isoformat(timespec='seconds')}\n"
            f"work_directory={work_directory}\n",
            encoding="utf-8",
        )

    def record(self, step: Step, elapsed_seconds: float, status: str) -> None:
        with self.path.open("a", encoding="utf-8") as output_file:
            output_file.write(
                f"{step.name}={elapsed_seconds:.3f}s status={status}\n"
            )

    def finish(self, elapsed_seconds: float, status: str) -> None:
        with self.path.open("a", encoding="utf-8") as output_file:
            output_file.write(
                f"total={elapsed_seconds:.3f}s status={status}\n"
            )


def _report_command_failure(
    step: Step,
    result: CommandResult,
    *,
    device: Optional[str] = None,
) -> None:
    target = f" for Device {device}" if device is not None else ""
    reason = "Timed Out" if result.timed_out else "Failed"
    print(
        f"[✗] {reason}: {step.description}{target} "
        f"after {_format_elapsed(result.elapsed_seconds)}",
        file=sys.stderr,
    )
    diagnostic = _diagnostic(result.output)
    if diagnostic:
        print(diagnostic, file=sys.stderr)


def run_serial_step(
    step: Step,
    work_directory: Path,
    timeout_seconds: float,
    *,
    verbose: bool,
) -> tuple[bool, float]:
    result = run_command(
        _step_command(step, work_directory),
        timeout_seconds=timeout_seconds,
    )
    if result.succeeded:
        if verbose and result.output.strip():
            print(result.output.rstrip())
        print(
            f"[✓] Completed: {step.description} "
            f"({_format_elapsed(result.elapsed_seconds)})"
        )
        return True, result.elapsed_seconds

    _report_command_failure(step, result)
    return False, result.elapsed_seconds


def run_device_step(
    step: Step,
    work_directory: Path,
    devices: Sequence[str],
    *,
    threads: int,
    deadline: float,
    verbose: bool,
) -> tuple[bool, float]:
    """Run all device commands against the shared pipeline deadline."""
    started_at = time.monotonic()

    def run_for_device(device: str) -> tuple[str, CommandResult]:
        remaining = deadline - time.monotonic()
        result = run_command(
            _step_command(step, work_directory, device=device),
            timeout_seconds=remaining,
        )
        return device, result

    failures: list[tuple[str, CommandResult]] = []
    uncertain_statuses: list[tuple[str, str]] = []
    successful_outputs: list[tuple[str, str]] = []
    worker_count = min(threads, len(devices))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(run_for_device, device): device
            for device in devices
        }
        for future in as_completed(futures):
            device = futures[future]
            try:
                _, result = future.result()
            except Exception as error:  # Preserve the failing device context.
                result = CommandResult(
                    None,
                    time.monotonic() - started_at,
                    f"Device task failed unexpectedly: {error}",
                )
            if not result.succeeded:
                failures.append((device, result))
            else:
                if verbose:
                    successful_outputs.append((device, result.output))
                else:
                    uncertain_statuses.extend(
                        (device, line)
                        for line in _uncertain_status_lines(result.output)
                    )

    elapsed_seconds = time.monotonic() - started_at
    for device, output in sorted(successful_outputs):
        if output.strip():
            print(f"Device {device}:")
            print(output.rstrip())
    for _, status_line in sorted(uncertain_statuses):
        print(status_line)
    if failures:
        for device, result in sorted(failures, key=lambda item: item[0]):
            _report_command_failure(step, result, device=device)
        return False, elapsed_seconds

    print(
        f"[✓] Completed: {step.description} for {len(devices)} Devices "
        f"({_format_elapsed(elapsed_seconds)})"
    )
    return True, elapsed_seconds


def run_pipeline(options: argparse.Namespace) -> bool:
    work_directory = options.work_directory.resolve()
    steps = build_steps(options)
    validate_inputs(work_directory, steps)
    validate_options(options, work_directory)
    devices = sorted(util_file.load_hostnames(work_directory))

    timing_report = TimingReport(
        _next_timing_file(work_directory), work_directory
    )
    pipeline_started_at = time.monotonic()
    pipeline_deadline = pipeline_started_at + options.timeout
    for step in steps:
        remaining_seconds = pipeline_deadline - time.monotonic()
        if remaining_seconds <= 0:
            print(
                f"[✗] Timed Out: SpecLens Pipeline before "
                f"{step.description}",
                file=sys.stderr,
            )
            timing_report.record(step, 0.0, "timed_out")
            timing_report.finish(
                time.monotonic() - pipeline_started_at, "timed_out"
            )
            return False

        if step.per_device:
            succeeded, elapsed_seconds = run_device_step(
                step,
                work_directory,
                devices,
                threads=options.threads,
                deadline=pipeline_deadline,
                verbose=options.verbose,
            )
        else:
            succeeded, elapsed_seconds = run_serial_step(
                step,
                work_directory,
                remaining_seconds,
                verbose=options.verbose,
            )

        timing_report.record(
            step, elapsed_seconds, "completed" if succeeded else "failed"
        )
        if not succeeded:
            timing_report.finish(
                time.monotonic() - pipeline_started_at, "failed"
            )
            return False

    timing_report.finish(
        time.monotonic() - pipeline_started_at, "completed"
    )
    return True


def _subspec_output_directories(
    options: argparse.Namespace,
    work_directory: Path,
) -> list[Path]:
    """Return final output directories for the selected workflows."""
    output_directories = []
    if options.subspec:
        output_directories.append(
            work_directory / util_keyword.SUBSPEC_DIR
        )
    if options.noscope:
        output_directories.append(
            work_directory / util_keyword.SUBSPEC_NOSCOPE_DIR
        )
    if options.fullsym:
        output_directories.append(
            work_directory / util_keyword.SUBSPEC_FULLSYM_DIR
        )
    return output_directories


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    try:
        succeeded = run_pipeline(options)
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as error:
        print(f"[✗] Failed: {error}", file=sys.stderr)
        return 1

    if not succeeded:
        print("[✗] Failed: SpecLens Pipeline", file=sys.stderr)
        return 1

    work_directory = options.work_directory.resolve()
    for output_directory in _subspec_output_directories(
        options, work_directory
    ):
        display_path = os.path.relpath(output_directory, Path.cwd())
        print(
            "[✓] Completed: Store Subspec Outputs to "
            f"'{display_path}'"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
