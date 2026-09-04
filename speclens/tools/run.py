#!/usr/bin/env python3
"""Run the SpecLens pipeline for one work directory."""

from __future__ import annotations

import argparse
import csv
import os
import re
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils import util_file, util_keyword  # noqa: E402
from tools.count import count_subspec_dir, count_subspecs  # noqa: E402
from tools.progress import TerminalSpinner  # noqa: E402


DEFAULT_THREADS = 1
DEFAULT_TIMEOUT_SECONDS = 4 * 60 * 60
PROCESS_TERMINATION_GRACE_SECONDS = 5
BENCHMARK_REPORT_FILE = "benchmark_time.csv"
BENCHMARK_COLUMNS = (
    "benchmark",
    "case",
    "step1.0",
    "step1.1",
    "step1.2",
    "step1.3",
    "step1.4",
    "step2.1",
    "step2.2",
    "step3.1",
    "step3.2",
    "step4.1",
    "step4.2",
    "field_non_empty",
    "field_all",
    "line_non_empty",
    "line_all",
)
STEP_COLUMNS = {
    "router_level_subspec": "step1.1",
    "router_local_encoding": "step1.2",
    "consistency_check": "step1.3",
    "internet2_refinement": "step1.4",
    "subspec_line": "step2.1",
    "subspec_field": "step2.2",
    "noscope_line": "step3.1",
    "noscope_field": "step3.2",
    "fullsym_line": "step4.1",
    "fullsym_field": "step4.2",
}
SUBSPEC_OUTPUT_BY_FINAL_STEP = {
    "subspec_field": util_keyword.SUBSPEC_DIR,
    "noscope_field": util_keyword.SUBSPEC_NOSCOPE_DIR,
    "fullsym_field": util_keyword.SUBSPEC_FULLSYM_DIR,
}
SUBSPEC_COUNT_BY_STEP = {
    "subspec_line": (util_keyword.SUBSPEC_DIR, "line"),
    "subspec_field": (util_keyword.SUBSPEC_DIR, "field"),
    "noscope_line": (util_keyword.SUBSPEC_NOSCOPE_DIR, "line"),
    "noscope_field": (util_keyword.SUBSPEC_NOSCOPE_DIR, "field"),
    "fullsym_line": (util_keyword.SUBSPEC_FULLSYM_DIR, "line"),
    "fullsym_field": (util_keyword.SUBSPEC_FULLSYM_DIR, "field"),
}
FIRST_SUBSPEC_STEPS = {"subspec_line", "noscope_line", "fullsym_line"}
PIPELINE_SEPARATOR = "-" * 70


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


@dataclass(frozen=True)
class StepRunResult:
    """Pipeline-visible result for one complete serial or device step."""

    succeeded: bool
    elapsed_seconds: float
    status: str


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
        description="Run the SpecLens pipeline for one work directory.",
        epilog=(
            "The default workflow is --subspec. The Stage 6 baseline is "
            "generated automatically during Stage 2."
        ),
    )
    workflows = parser.add_argument_group("subspecification workflows")
    workflow = workflows.add_mutually_exclusive_group()
    workflow.add_argument(
        "--subspec",
        action="store_true",
        help="run Stages 1, 2, 3, and 4",
    )
    workflow.add_argument(
        "--noscope",
        action="store_true",
        help="run Stages 1, 2, 3, and 5",
    )
    workflow.add_argument(
        "--fullsym",
        action="store_true",
        help="run Stages 2 and 6",
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
        dest="community",
        help="enable community subspecification in selected stages",
    )
    parser.add_argument(
        "--threads",
        type=_positive_int,
        default=DEFAULT_THREADS,
        help=f"maximum concurrent device tasks (default: {DEFAULT_THREADS})",
    )
    parser.add_argument(
        "--timeout",
        type=_duration_seconds,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="DURATION",
        help=(
            "timeout for the entire selected workflow "
            "(for example: 7200, 2h, or 1h30m; default: 4h)"
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
        "--benchmark",
        default="-",
        metavar="NAME",
        help="benchmark label stored in benchmark_time.csv (default: -)",
    )
    parser.add_argument(
        "work_directory",
        type=Path,
        help="work directory containing the SMT and simulation inputs",
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


def _selected_stages(options: argparse.Namespace) -> tuple[bool, bool, bool]:
    if options.all:
        return True, True, True
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
        fullsym_argument = ("--fullsym-baseline",) if run_fullsym else ()
        encoding_description = (
            "Global Encoding and Global Encoding Subspec"
            if run_fullsym and not run_standard_pipeline
            else "Router-Local Slice Encoding"
        )
        steps.append(
            Step(
                "router_local_encoding",
                encoding_description,
                "2_router_local_encoding.py",
                fullsym_argument + verbose_argument,
            )
        )
    if run_standard_pipeline:
        if options.internet2:
            steps.extend(
                [
                    Step(
                        "consistency_check",
                        "Initial Internet2 Consistency Check",
                        "3_consistency_checker.py",
                        ("--internet2-initial",) + verbose_argument,
                        per_device=True,
                    ),
                    Step(
                        "internet2_refinement",
                        "Internet2 Consistency Refinement",
                        "3_consistency_checker.py",
                        ("--internet2-refine",) + verbose_argument,
                        per_device=True,
                    ),
                ]
            )
        else:
            steps.append(
                Step(
                    "consistency_check",
                    "Consistency Check",
                    "3_consistency_checker.py",
                    verbose_argument,
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
                    ("-l",) + community_argument + verbose_argument,
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


def validate_options(options: argparse.Namespace) -> None:
    run_subspec, run_noscope, _ = _selected_stages(options)
    if options.internet2 and not (run_subspec or run_noscope):
        raise ValueError(
            "--internet2 requires --subspec or --noscope because "
            "--fullsym does not run the consistency checker"
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


class BenchmarkReport:
    """Write one benchmark-compatible CSV row for an SMT case."""

    def __init__(
        self,
        work_directory: Path,
        options: argparse.Namespace,
    ) -> None:
        self.path = work_directory / BENCHMARK_REPORT_FILE
        self.work_directory = work_directory
        self.values = {column: "-" for column in BENCHMARK_COLUMNS}
        self.values["benchmark"] = options.benchmark
        self.values["case"] = work_directory.name
        self.values["step1.0"] = "0s"
        run_subspec, run_noscope, _ = _selected_stages(options)
        if (run_subspec or run_noscope) and not options.internet2:
            self.values["step1.4"] = "0s"
        self.completed_columns: set[str] = set()

    def record(self, step: Step, result: StepRunResult) -> None:
        column = STEP_COLUMNS[step.name]
        if result.status == "timed_out":
            value = "4h+"
        elif result.status == "failed":
            value = "ERROR"
        else:
            value = _format_elapsed(result.elapsed_seconds)
            self.completed_columns.add(column)
        self.values[column] = value

    def _record_subspec_counts(self) -> None:
        required = {"step2.1", "step2.2"}
        if not required.issubset(self.completed_columns):
            return
        counts = count_subspecs(self.work_directory)
        self.values.update(
            {
                "field_non_empty": str(counts.field.non_empty),
                "field_all": str(counts.field.total),
                "line_non_empty": str(counts.line.non_empty),
                "line_all": str(counts.line.total),
            }
        )

    def write(self) -> None:
        self._record_subspec_counts()
        with self.path.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=BENCHMARK_COLUMNS)
            writer.writeheader()
            writer.writerow(self.values)


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
) -> StepRunResult:
    with TerminalSpinner(f"Running: {step.description}"):
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
        return StepRunResult(True, result.elapsed_seconds, "completed")

    _report_command_failure(step, result)
    status = "timed_out" if result.timed_out else "failed"
    return StepRunResult(False, result.elapsed_seconds, status)


def run_device_step(
    step: Step,
    work_directory: Path,
    devices: Sequence[str],
    *,
    threads: int,
    deadline: float,
    verbose: bool,
) -> StepRunResult:
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
    completed_count = 0
    progress = TerminalSpinner(
        f"Running: {step.description} (0/{len(devices)} Devices)"
    )
    with progress:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(run_for_device, device): device
                for device in devices
            }
            for future in as_completed(futures):
                device = futures[future]
                try:
                    _, result = future.result()
                except Exception as error:  # Preserve the device context.
                    result = CommandResult(
                        None,
                        time.monotonic() - started_at,
                        f"Device task failed unexpectedly: {error}",
                    )
                if not result.succeeded:
                    failures.append((device, result))
                elif verbose:
                    successful_outputs.append((device, result.output))
                else:
                    uncertain_statuses.extend(
                        (device, line)
                        for line in _uncertain_status_lines(result.output)
                    )
                completed_count += 1
                progress.update(
                    f"Running: {step.description} "
                    f"({completed_count}/{len(devices)} Devices)"
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
        status = (
            "timed_out"
            if any(result.timed_out for _, result in failures)
            else "failed"
        )
        return StepRunResult(False, elapsed_seconds, status)

    completion_details = [_format_elapsed(elapsed_seconds)]
    count_spec = SUBSPEC_COUNT_BY_STEP.get(step.name)
    if count_spec is not None:
        directory_name, level_name = count_spec
        counts = count_subspec_dir(work_directory / directory_name)
        level_counts = getattr(counts, level_name)
        completion_details.append(
            f"#subspec {level_counts.non_empty}/{level_counts.total}"
        )
    print(
        f"[✓] Completed: {step.description} for {len(devices)} Devices "
        f"({', '.join(completion_details)})"
    )
    return StepRunResult(True, elapsed_seconds, "completed")


def _report_subspec_output(step: Step, work_directory: Path) -> None:
    """Report a workflow output immediately after its final step."""
    directory_name = SUBSPEC_OUTPUT_BY_FINAL_STEP.get(step.name)
    if directory_name is None:
        return
    output_directory = work_directory / directory_name
    display_path = os.path.relpath(output_directory, Path.cwd())
    print(
        "[✓] Completed: Store Subspec Outputs to "
        f"'{display_path}'"
    )


def run_pipeline(options: argparse.Namespace) -> bool:
    work_directory = options.work_directory.resolve()
    steps = build_steps(options)
    validate_inputs(work_directory, steps)
    validate_options(options)
    devices = sorted(util_file.load_hostnames(work_directory))

    benchmark_report = BenchmarkReport(work_directory, options)
    pipeline_started_at = time.monotonic()
    pipeline_deadline = pipeline_started_at + options.timeout
    subspec_separator_printed = False
    try:
        for step_index, step in enumerate(steps):
            if (
                step.name in FIRST_SUBSPEC_STEPS
                and not subspec_separator_printed
            ):
                print(PIPELINE_SEPARATOR)
                subspec_separator_printed = True
            remaining_seconds = pipeline_deadline - time.monotonic()
            if remaining_seconds <= 0:
                print(
                    f"[✗] Timed Out: SpecLens Pipeline before "
                    f"{step.description}",
                    file=sys.stderr,
                )
                benchmark_report.record(
                    step,
                    StepRunResult(False, 0.0, "timed_out"),
                )
                return False

            if step.per_device:
                result = run_device_step(
                    step,
                    work_directory,
                    devices,
                    threads=options.threads,
                    deadline=pipeline_deadline,
                    verbose=options.verbose,
                )
            else:
                result = run_serial_step(
                    step,
                    work_directory,
                    remaining_seconds,
                    verbose=options.verbose,
                )

            benchmark_report.record(step, result)
            if not result.succeeded:
                return False
            _report_subspec_output(step, work_directory)
            if (
                step.name in SUBSPEC_OUTPUT_BY_FINAL_STEP
                and step_index < len(steps) - 1
            ):
                print(PIPELINE_SEPARATOR)
        return True
    finally:
        benchmark_report.write()


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
    benchmark_report = os.path.relpath(
        work_directory / BENCHMARK_REPORT_FILE,
        Path.cwd(),
    )
    print(
        "[✓] Completed: Store Benchmark Timing to "
        f"'{benchmark_report}'"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
