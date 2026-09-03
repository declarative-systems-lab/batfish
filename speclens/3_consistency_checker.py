#!/usr/bin/env python3
"""Generate and check router consistency SMT encodings.

Stage 3 appends each router's satisfaction and violation assume-guarantee
fragments to its local encoding, runs Z3, and optionally computes route-map
subspecs.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from utils import util_keyword
from utils.util_file import (
    delete_consistency_checker_outputs,
    delete_router_consistency_outputs,
    ensure_directory,
    load_consistency_encoding,
    load_consistency_routers,
    load_router_assume_guarantee,
    load_router_local_encoding,
    load_routers_from_local_encodings,
    load_text,
    patch_internet2_violation_encoding,
    patch_internet2_violation_encodings,
    reconstruct_internet2_constraints_from_model,
    update_router_assume_guarantee_declarations,
    validate_consistency_checker_inputs,
    violation_check_file_name,
    write_consistency_encoding,
    write_consistency_summary,
)
from utils.util_log import (
    exit_with_error,
    log_error,
    log_info,
    verbose_info,
)
from utils.util_smt import (
    build_consistency_smt,
    check_smt_satisfiability,
    extract_smt_declaration_map,
    run_z3_get_model,
)
from utils.util_subspec_routemap import RoutemapSubspecCalculator


CheckResult = Tuple[bool, str]
RouterCheckResults = Dict[str, CheckResult]
ConsistencyResults = Dict[str, RouterCheckResults]
ConsistencyFailures = Dict[str, List[str]]
INTERNET2_INITIAL_RESULTS_FILE = ".internet2_initial_results"


class ConsistencyEncodingBuilder:
    """Combine router-local encodings with stage-1 assume-guarantees."""

    def __init__(
        self,
        work_dir: str,
        routers: Optional[Sequence[str]] = None,
        verbose_flag: bool = False,
    ):
        self.work_dir = Path(work_dir)
        self.verbose_flag = verbose_flag
        ensure_directory(self.work_dir / util_keyword.CONSISTENCY_CHECK_DIR)
        self.all_routers = load_routers_from_local_encodings(self.work_dir)
        self.routers = tuple(routers or self.all_routers)
        self._synchronize_assume_guarantee_declarations()

    def _synchronize_assume_guarantee_declarations(self) -> None:
        """Make declarations from every local slice available to AG fragments."""
        available_declarations = {}
        for router in self.all_routers:
            local_encoding = load_router_local_encoding(self.work_dir, router)
            available_declarations.update(
                extract_smt_declaration_map(local_encoding)
            )

        for router in self.routers:
            update_router_assume_guarantee_declarations(
                self.work_dir,
                router,
                available_declarations,
            )

    def _build_encoding(self, router: str, *, satisfaction: bool) -> str:
        """Build one complete satisfaction or violation query."""
        check_name = "satisfaction" if satisfaction else "violation"
        verbose_info(
            self.verbose_flag,
            f"Generating {check_name} file for device: {router}",
        )
        local_encoding = load_router_local_encoding(self.work_dir, router)
        assume_guarantee = load_router_assume_guarantee(
            self.work_dir,
            router,
            satisfaction=satisfaction,
        )
        return build_consistency_smt(local_encoding, assume_guarantee)

    def write_router_encodings(self, router: str) -> Tuple[bool, str]:
        """Write the satisfaction and violation queries for one router."""
        try:
            for satisfaction in (True, False):
                content = self._build_encoding(
                    router,
                    satisfaction=satisfaction,
                )
                output_file = write_consistency_encoding(
                    self.work_dir,
                    router,
                    content,
                    satisfaction=satisfaction,
                )
                verbose_info(
                    self.verbose_flag,
                    f"Generated: {output_file}",
                )
        except Exception as error:
            return False, f"Error generating files for device {router}: {error}"
        return True, f"Generated files for device {router}"

    def write_all_router_encodings(self) -> None:
        """Write both consistency queries for every selected router."""
        for router in self.routers:
            success, message = self.write_router_encodings(router)
            if not success:
                raise RuntimeError(message)


class ConsistencyChecker:
    """Generate router consistency queries and evaluate them with Z3."""

    def __init__(
        self,
        work_dir: str,
        device_filter: Optional[str] = None,
        verbose_flag: bool = False,
    ):
        self.work_dir = Path(work_dir)
        self.device_filter = device_filter
        self.verbose_flag = verbose_flag
        self.output_dir = ensure_directory(
            self.work_dir / util_keyword.CONSISTENCY_CHECK_DIR
        )
        self.routers = load_consistency_routers(
            self.work_dir,
            router_filter=device_filter,
        )

    def _test_encoding(self, router: str, *, satisfaction: bool) -> CheckResult:
        """Run one generated consistency query with Z3."""
        check_name = "satisfaction" if satisfaction else "violation"
        verbose_info(
            self.verbose_flag,
            f"Testing {check_name} for device: {router}",
        )
        try:
            content = load_consistency_encoding(
                self.work_dir,
                router,
                satisfaction=satisfaction,
            )
        except FileNotFoundError as error:
            log_error(str(error))
            return False, str(error)
        return check_smt_satisfiability(content)

    def test_satisfaction(self, router: str) -> CheckResult:
        """Run the satisfaction query for one router."""
        return self._test_encoding(router, satisfaction=True)

    def test_violation(self, router: str) -> CheckResult:
        """Run the violation query for one router."""
        return self._test_encoding(router, satisfaction=False)

    def _check_router(self, router: str) -> RouterCheckResults:
        """Check both generated consistency queries for one router."""
        verbose_info(self.verbose_flag, "=" * 60)
        verbose_info(self.verbose_flag, f"Processing device: {router}")
        verbose_info(self.verbose_flag, "=" * 60)

        satisfaction_result = self.test_satisfaction(router)
        violation_result = self.test_violation(router)
        results = {
            "satisfaction": satisfaction_result,
            "violation": violation_result,
        }
        self._report_check_result(router, results)
        return results

    def _report_check_result(
        self,
        router: str,
        results: RouterCheckResults,
    ) -> None:
        """Report the expected SAT/UNSAT outcome for one router."""
        satisfaction_sat, _ = results["satisfaction"]
        violation_sat, _ = results["violation"]
        verbose_info(
            self.verbose_flag,
            f"Satisfaction result: {'SAT' if satisfaction_sat else 'UNSAT'}",
        )
        verbose_info(
            self.verbose_flag,
            f"Violation result: {'SAT' if violation_sat else 'UNSAT'}",
        )

    @staticmethod
    def _router_passed(results: RouterCheckResults) -> bool:
        satisfaction_sat, _ = results["satisfaction"]
        violation_sat, _ = results["violation"]
        return satisfaction_sat and not violation_sat

    def check_all_routers(
        self,
        parallel: bool = False,
        max_workers: Optional[int] = None,
    ) -> ConsistencyResults:
        """Check generated satisfaction and violation queries for all routers."""
        return self._check_routers(self.routers, parallel, max_workers)

    def _check_routers(
        self,
        routers: Sequence[str],
        parallel: bool = False,
        max_workers: Optional[int] = None,
    ) -> ConsistencyResults:
        """Check both consistency queries for the selected routers."""
        verbose_info(
            self.verbose_flag,
            f"Running assume-guarantee tests for {len(routers)} devices",
        )
        verbose_info(self.verbose_flag, f"Devices: {list(routers)}")

        if parallel and len(routers) > 1:
            return self._check_routers_parallel(routers, max_workers)

        verbose_info(self.verbose_flag, "Running tests serially...")
        results = {}
        for router in routers:
            router_results = self._check_router(router)
            results[router] = router_results
        return results

    def _check_routers_parallel(
        self,
        routers: Sequence[str],
        max_workers: Optional[int],
    ) -> ConsistencyResults:
        """Generate and check routers concurrently."""
        worker_count = max_workers or len(routers)
        verbose_info(
            self.verbose_flag,
            f"Running tests in parallel (max_workers={worker_count})...",
        )
        results = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._check_router, router): router
                for router in routers
            }
            for future in as_completed(futures):
                router = futures[future]
                try:
                    router_results = future.result()
                except Exception as error:
                    log_error(f"Error testing device {router}: {error}")
                    router_results = {
                        "satisfaction": (False, f"Error: {error}"),
                        "violation": (False, f"Error: {error}"),
                    }
                results[router] = router_results
        return results

    def write_summary(self, results: ConsistencyResults) -> None:
        """Write the consistency result summary and report failures."""
        verbose_info(self.verbose_flag, "=" * 80)
        verbose_info(self.verbose_flag, "ASSUME-GUARANTEE TEST SUMMARY")
        verbose_info(self.verbose_flag, "=" * 80)

        summary_lines = [
            "=" * 80,
            "ASSUME-GUARANTEE TEST SUMMARY",
            "=" * 80,
            "",
        ]
        failures_by_router: Dict[str, List[str]] = {}
        for router, router_results in results.items():
            satisfaction_sat, satisfaction_output = router_results[
                "satisfaction"
            ]
            violation_sat, violation_output = router_results["violation"]
            status = "PASS" if self._router_passed(router_results) else "FAIL"
            result_line = (
                f"Device {router:25} | Satisfaction: "
                f"{'SAT' if satisfaction_sat else 'UNSAT':5} | Violation: "
                f"{'SAT' if violation_sat else 'UNSAT':5} | Status: {status}"
            )
            verbose_info(self.verbose_flag, result_line)
            summary_lines.append(result_line)

            if not satisfaction_sat:
                self._record_failure(
                    summary_lines,
                    failures_by_router,
                    router,
                    "satisfaction",
                    satisfaction_output,
                )
            if violation_sat:
                self._record_failure(
                    summary_lines,
                    failures_by_router,
                    router,
                    "violation",
                    violation_output,
                )

        summary_lines.extend(
            [
                "",
                f"Total devices tested: {len(results)}",
                f"Failed devices: {len(failures_by_router)}",
            ]
        )
        verbose_info(
            self.verbose_flag,
            f"\nTotal devices tested: {len(results)}",
        )
        verbose_info(
            self.verbose_flag,
            f"Failed devices: {len(failures_by_router)}",
        )
        self._append_summary_status(summary_lines, failures_by_router)

        try:
            summary_file = write_consistency_summary(
                self.work_dir,
                summary_lines,
                router_filter=self.device_filter,
            )
            verbose_info(
                self.verbose_flag,
                f"\nTest summary saved to: {summary_file}",
            )
        except OSError as error:
            log_error(f"Failed to save test summary: {error}")

    @staticmethod
    def _record_failure(
        summary_lines: List[str],
        failures_by_router: Dict[str, List[str]],
        router: str,
        check_name: str,
        diagnostic: str,
    ) -> None:
        message = (
            f"  {check_name.title()} check failed for {router}: {diagnostic}"
        )
        summary_lines.append(message)
        failures_by_router.setdefault(router, []).append(check_name)

    def _append_summary_status(
        self,
        summary_lines: List[str],
        failures_by_router: Dict[str, List[str]],
    ) -> None:
        if not failures_by_router:
            message = "All tests passed! ✓"
            verbose_info(self.verbose_flag, message)
            summary_lines.append(message)
            return

        failures = [
            f"{router} ({', '.join(check_names)})"
            for router, check_names in sorted(failures_by_router.items())
        ]
        message = f"Failed devices: {', '.join(failures)}"
        summary_lines.append(message)

    def all_checks_passed(self, results: ConsistencyResults) -> bool:
        """Return whether satisfaction is SAT and violation is UNSAT."""
        return all(self._router_passed(result) for result in results.values())

    def calculate_routemap_subspecs(
        self,
        parallel: bool = False,
        max_workers: Optional[int] = None,
    ) -> None:
        """Calculate route-map subspecs from satisfaction-check models."""
        if parallel and len(self.routers) > 1:
            self._calculate_routemap_subspecs_parallel(max_workers)
            return

        calculator = RoutemapSubspecCalculator(
            self.work_dir,
            self.routers,
            self.output_dir,
            device_filter=None,
        )
        calculator.calculate_routemap_subspecs()

    def _calculate_routemap_subspecs_parallel(
        self,
        max_workers: Optional[int],
    ) -> None:
        """Calculate one route-map subspec file per router concurrently."""
        worker_count = max_workers or len(self.routers)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    self._calculate_router_routemap_subspecs,
                    router,
                ): router
                for router in self.routers
            }
            for future in as_completed(futures):
                router = futures[future]
                try:
                    future.result()
                    if not self.verbose_flag:
                        print(
                            f"Device {router}: ✓ Route-map level subspecs "
                            "completed"
                        )
                except Exception as error:
                    log_error(
                        "Error calculating route-map level subspecs for "
                        f"device {router}: {error}"
                    )

    def _calculate_router_routemap_subspecs(self, router: str) -> None:
        """Calculate route-map subspecs for one router."""
        calculator = RoutemapSubspecCalculator(
            self.work_dir,
            [router],
            self.output_dir,
            device_filter=router,
        )
        calculator.calculate_routemap_subspecs()


class Internet2ConsistencyRefiner:
    """Refine violation-SAT routers from their Z3 models."""

    def __init__(
        self,
        checker: ConsistencyChecker,
        builder: ConsistencyEncodingBuilder,
    ):
        self.checker = checker
        self.builder = builder
        self.work_dir = checker.work_dir
        self.verbose_flag = checker.verbose_flag

    def patch_generated_violations(self) -> None:
        """Disable external BGP environment routes before initial checks."""
        summary = patch_internet2_violation_encodings(
            self.work_dir,
            router_filter=self.checker.device_filter,
        )
        if summary.errors:
            raise RuntimeError(
                f"Failed to patch {summary.errors} Internet2 violation file(s)"
            )
        verbose_info(
            self.verbose_flag,
            "Patched %d Internet2 violation file(s) with %d EXPORT_ENV "
            "assumption(s).",
            summary.processed_files,
            summary.inserted_assertions,
        )

    def refine_failures(
        self,
        results: ConsistencyResults,
    ) -> Tuple[ConsistencyResults, int]:
        """Refine violation-SAT routers, regenerate, and recheck them."""
        candidates = sorted(
            router
            for router, router_results in results.items()
            if router_results["violation"][0]
        )
        if not candidates:
            return results, 0

        verbose_info(
            self.verbose_flag,
            "Refining violation-SAT routers from Z3 models: %s",
            ", ".join(candidates),
        )
        refined_routers = []
        for router in candidates:
            if self._refine_router(router):
                refined_routers.append(router)

        if not refined_routers:
            return results, 0

        refined_results = self.checker._check_routers(refined_routers)
        results.update(refined_results)
        return results, len(refined_routers)

    def _refine_router(self, router: str) -> bool:
        """Apply one violation model to a router's assume-guarantees."""
        violation_file = (
            self.work_dir
            / util_keyword.CONSISTENCY_CHECK_DIR
            / violation_check_file_name(router)
        )
        is_sat, status, model = run_z3_get_model(load_text(violation_file))
        if not is_sat:
            verbose_info(
                self.verbose_flag,
                "%s: expected violation SAT for get-model, got %s",
                router,
                status,
            )
            return False

        reconstruction = reconstruct_internet2_constraints_from_model(
            self.work_dir,
            router,
            model,
        )
        verbose_info(
            self.verbose_flag,
            "%s: model refined %d value(s), matched %d/%d variable(s)",
            router,
            reconstruction.changed_values,
            reconstruction.matched_variables,
            reconstruction.total_variables,
        )
        if reconstruction.missing_variables:
            verbose_info(
                self.verbose_flag,
                "%s: %d variable(s) were absent from the model",
                router,
                len(reconstruction.missing_variables),
            )

        success, message = self.builder.write_router_encodings(router)
        if not success:
            raise RuntimeError(message)
        patch_internet2_violation_encoding(
            self.work_dir
            / util_keyword.CONSISTENCY_CHECK_DIR
            / violation_check_file_name(router)
        )
        return True


def _parse_cli_args(
    args: Sequence[str],
) -> Tuple[
    bool,
    bool,
    bool,
    bool,
    bool,
    bool,
    Optional[str],
    Optional[str],
]:
    verbose_flag = False
    delete_flag = False
    routemap_subspec = False
    internet2 = False
    internet2_initial = False
    internet2_refine = False
    router_filter = None
    work_dir = None
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "-v":
            verbose_flag = True
        elif argument == "-d":
            delete_flag = True
        elif argument == "-r":
            routemap_subspec = True
        elif argument == "--internet2":
            internet2 = True
        elif argument == "--internet2-initial":
            internet2_initial = True
        elif argument == "--internet2-refine":
            internet2_refine = True
        elif argument == "--device":
            if index + 1 >= len(args) or args[index + 1].startswith("-"):
                raise ValueError("--device requires a value")
            if router_filter is not None:
                raise ValueError("--device specified multiple times")
            router_filter = args[index + 1]
            index += 1
        elif argument.startswith("-"):
            raise ValueError(f"Unknown option: {argument}")
        elif work_dir is not None:
            raise ValueError("Multiple work directories specified")
        else:
            work_dir = argument
        index += 1
    if sum((internet2, internet2_initial, internet2_refine)) > 1:
        raise ValueError(
            "--internet2, --internet2-initial, and --internet2-refine "
            "are mutually exclusive"
        )
    return (
        verbose_flag,
        delete_flag,
        routemap_subspec,
        internet2,
        internet2_initial,
        internet2_refine,
        router_filter,
        work_dir,
    )


def _print_usage() -> None:
    print(
        "Usage: python 3_consistency_checker.py [-v] [-d] [-r] "
        "[--internet2 | --internet2-initial | --internet2-refine] "
        "[--device DEVICE] <work_directory>"
    )
    print("Options:")
    print("  -v     Verbose mode: Show detailed INFO logs")
    print("         Without -v: Only show WARNING/ERROR logs and completion status")
    print("  -d     Delete intermediate output files before running, then exit")
    print("  -r     If all tests pass, compute route-map functional subspecs")
    print("  --internet2      Refine assume-guarantee from Z3 models")
    print("  --internet2-initial  Run and persist the initial Internet2 checks")
    print("  --internet2-refine   Refine the persisted Internet2 check failures")
    print("  --device DEVICE  Process only the specified device")
    print("                   Without --device DEVICE: Process all devices")
    print("  -h, --help       Show this help message")
    print("")
    print("Example: python 3_consistency_checker.py smt_output_0001")
    print("         python 3_consistency_checker.py -v smt_output_0001")
    print("         python 3_consistency_checker.py -d smt_output_0001")
    print("         python 3_consistency_checker.py -r smt_output_0001")
    print("         python 3_consistency_checker.py --internet2 smt_output_0001")
    print("         python 3_consistency_checker.py --device r1 smt_output_0001")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by stage 3 and report the result."""
    deleted_paths = delete_consistency_checker_outputs(work_dir)
    if not deleted_paths:
        log_info("No intermediate files found to delete.")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted intermediate output: %s", deleted_path)


def _prepare_consistency_checks(
    work_dir: Path,
    *,
    router_filter: Optional[str],
    verbose_flag: bool,
) -> Tuple[ConsistencyChecker, ConsistencyEncodingBuilder]:
    """Validate inputs, replace prior outputs, and generate check encodings."""
    validate_consistency_checker_inputs(work_dir)
    if router_filter is None:
        delete_consistency_checker_outputs(work_dir)
    else:
        delete_router_consistency_outputs(work_dir, router_filter)
    checker = ConsistencyChecker(
        str(work_dir),
        device_filter=router_filter,
        verbose_flag=verbose_flag,
    )
    builder = ConsistencyEncodingBuilder(
        str(work_dir),
        routers=checker.routers,
        verbose_flag=verbose_flag,
    )
    builder.write_all_router_encodings()
    return checker, builder


def _internet2_results_path(
    work_dir: Path,
    router_filter: Optional[str],
) -> Path:
    suffix = f"_{router_filter}" if router_filter else ""
    return (
        work_dir
        / util_keyword.CONSISTENCY_CHECK_DIR
        / f"{INTERNET2_INITIAL_RESULTS_FILE}{suffix}.json"
    )


def _save_internet2_initial_results(
    work_dir: Path,
    router_filter: Optional[str],
    results: ConsistencyResults,
) -> None:
    path = _internet2_results_path(work_dir, router_filter)
    path.write_text(json.dumps(results), encoding="utf-8")


def _load_internet2_initial_results(
    work_dir: Path,
    router_filter: Optional[str],
) -> ConsistencyResults:
    path = _internet2_results_path(work_dir, router_filter)
    if not path.is_file():
        raise FileNotFoundError(
            f"Internet2 initial-check results not found: {path}"
        )
    raw_results = json.loads(path.read_text(encoding="utf-8"))
    results: ConsistencyResults = {}
    for router, router_results in raw_results.items():
        results[router] = {
            check_name: (bool(check_result[0]), str(check_result[1]))
            for check_name, check_result in router_results.items()
        }
    return results


def _finish_consistency_checks(
    checker: ConsistencyChecker,
    results: ConsistencyResults,
    *,
    routemap_subspec: bool,
    verbose_flag: bool,
) -> None:
    if checker.all_checks_passed(results) and routemap_subspec:
        verbose_info(verbose_flag, "=" * 80)
        verbose_info(
            verbose_flag,
            "All tests passed! Calculating route-map level subspecs "
            "(-r enabled)...",
        )
        verbose_info(verbose_flag, "=" * 80)
        checker.calculate_routemap_subspecs(parallel=False)
    elif not checker.all_checks_passed(results):
        verbose_info(
            verbose_flag,
            "Some tests failed. Skipping route-map level subspec calculation.",
        )


def _run_consistency_checks(
    work_dir: Path,
    *,
    routemap_subspec: bool,
    internet2: bool,
    router_filter: Optional[str],
    verbose_flag: bool,
) -> Tuple[ConsistencyResults, bool, ConsistencyFailures]:
    """Run consistency checks and optional route-map subspec calculation."""
    checker, builder = _prepare_consistency_checks(
        work_dir,
        router_filter=router_filter,
        verbose_flag=verbose_flag,
    )
    refiner = None
    if internet2:
        refiner = Internet2ConsistencyRefiner(checker, builder)
        refiner.patch_generated_violations()

    # Check and summarize.
    results = checker.check_all_routers(parallel=False)
    checker.write_summary(results)
    initial_failures = _collect_consistency_failures(results) if internet2 else {}

    # Internet2 violation models replace only the failed route constraints.
    refined_count = 0
    if refiner is not None and not checker.all_checks_passed(results):
        results, refined_count = refiner.refine_failures(results)
        if refined_count:
            checker.write_summary(results)

    _finish_consistency_checks(
        checker,
        results,
        routemap_subspec=routemap_subspec,
        verbose_flag=verbose_flag,
    )
    return results, refined_count > 0, initial_failures


def _run_internet2_initial_checks(
    work_dir: Path,
    *,
    router_filter: Optional[str],
    verbose_flag: bool,
) -> ConsistencyResults:
    """Run and persist the initial Internet2 checks for later refinement."""
    checker, builder = _prepare_consistency_checks(
        work_dir,
        router_filter=router_filter,
        verbose_flag=verbose_flag,
    )
    Internet2ConsistencyRefiner(checker, builder).patch_generated_violations()
    results = checker.check_all_routers(parallel=False)
    checker.write_summary(results)
    _save_internet2_initial_results(work_dir, router_filter, results)
    return results


def _run_internet2_refinement(
    work_dir: Path,
    *,
    routemap_subspec: bool,
    router_filter: Optional[str],
    verbose_flag: bool,
) -> Tuple[ConsistencyResults, bool]:
    """Refine the persisted Internet2 failures without repeating initial checks."""
    validate_consistency_checker_inputs(work_dir)
    results_path = _internet2_results_path(work_dir, router_filter)
    results = _load_internet2_initial_results(work_dir, router_filter)
    checker = ConsistencyChecker(
        str(work_dir),
        device_filter=router_filter,
        verbose_flag=verbose_flag,
    )
    builder = ConsistencyEncodingBuilder(
        str(work_dir),
        routers=checker.routers,
        verbose_flag=verbose_flag,
    )
    refiner = Internet2ConsistencyRefiner(checker, builder)
    results, refined_count = refiner.refine_failures(results)
    if refined_count:
        checker.write_summary(results)
    _finish_consistency_checks(
        checker,
        results,
        routemap_subspec=routemap_subspec,
        verbose_flag=verbose_flag,
    )
    results_path.unlink()
    return results, refined_count > 0


def _collect_consistency_failures(
    results: ConsistencyResults,
) -> ConsistencyFailures:
    """Collect failed satisfaction and violation checks by router."""
    failures = {}
    for router, router_results in sorted(results.items()):
        failed_checks = []
        if not router_results["satisfaction"][0]:
            failed_checks.append("satisfaction")
        if router_results["violation"][0]:
            failed_checks.append("violation")
        if failed_checks:
            failures[router] = failed_checks
    return failures


def _print_internet2_initial_status(
    results: ConsistencyResults,
    *,
    router_filter: Optional[str],
) -> None:
    """Report initial failures as refinable without failing the phase."""
    for router, failed_checks in sorted(
        _collect_consistency_failures(results).items()
    ):
        print(
            "[?] Failed: Initial Consistency Check Failed for Device "
            f"{router}: {' / '.join(failed_checks)}"
        )
    message = "[✓] Completed: Initial Internet2 Consistency Check"
    if router_filter is not None:
        message += f" for Device {router_filter}"
    print(message)


def _print_final_status(
    results: ConsistencyResults,
    *,
    router_filter: Optional[str],
    refined: bool,
    initial_failures: ConsistencyFailures,
) -> bool:
    """Print only the final success or per-router failure status."""
    for router, failed_checks in sorted(initial_failures.items()):
        print(
            "[?] Failed: Consistency Check Failed for Device "
            f"{router}: {' / '.join(failed_checks)}"
        )

    final_failures = _collect_consistency_failures(results)
    for router, failed_checks in sorted(final_failures.items()):
        print(
            "[✗] Failed: Consistency Check Failed for Device "
            f"{router}: {' / '.join(failed_checks)}"
        )
    if final_failures:
        return False

    message = "[✓] Completed: Consistency Check"
    if router_filter is not None:
        message += f" for Device {router_filter}"
    if refined:
        message += " after Internet2 Refinement"
    print(message)
    return True


def main(args: Optional[Sequence[str]] = None) -> None:
    """Run the stage-3 consistency checking pipeline."""
    cli_args = list(sys.argv[1:] if args is None else args)
    if any(argument in ("-h", "--help") for argument in cli_args):
        _print_usage()
        return
    if not cli_args:
        _print_usage()
        exit_with_error("Work directory is required")

    try:
        (
            verbose_flag,
            delete_flag,
            routemap_subspec,
            internet2,
            internet2_initial,
            internet2_refine,
            router_filter,
            work_dir,
        ) = _parse_cli_args(cli_args)
    except ValueError as error:
        exit_with_error(f"Error: {error}")

    if not work_dir:
        _print_usage()
        exit_with_error("Work directory is required")

    work_dir_path = Path(work_dir)
    if not work_dir_path.is_dir():
        _print_usage()
        exit_with_error(
            "Work directory does not exist or is not a directory: "
            f"{work_dir_path}"
        )

    if delete_flag:
        _delete_outputs(work_dir_path)
        return

    try:
        if internet2_initial:
            results = _run_internet2_initial_checks(
                work_dir_path,
                router_filter=router_filter,
                verbose_flag=verbose_flag,
            )
            _print_internet2_initial_status(
                results,
                router_filter=router_filter,
            )
            return

        if internet2_refine:
            results, refined = _run_internet2_refinement(
                work_dir_path,
                routemap_subspec=routemap_subspec,
                router_filter=router_filter,
                verbose_flag=verbose_flag,
            )
            initial_failures = {}
        else:
            results, refined, initial_failures = _run_consistency_checks(
                work_dir_path,
                routemap_subspec=routemap_subspec,
                internet2=internet2,
                router_filter=router_filter,
                verbose_flag=verbose_flag,
            )
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if not _print_final_status(
        results,
        router_filter=router_filter,
        refined=refined,
        initial_failures=initial_failures,
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
