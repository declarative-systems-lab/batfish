#!/usr/bin/env python3
"""Build property-scoped and router-local SMT encodings.

Each router slice contains all peers' best routes and export policies, then
the local import policies, best-route selection, and final best route.
"""

import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from utils import util_keyword
from utils.util_data import RouterLocalEncodingState
from utils.util_file import (
    clear_router_local_encoding_files,
    delete_router_local_encoding_outputs,
    ensure_directory,
    load_hostnames,
    load_optional_model_igp,
    load_smt_source_lines,
    load_target_smt_variables,
    update_router_assume_guarantee_declarations,
    validate_router_local_encoding_inputs,
    validate_router_local_encoding_outputs,
    write_router_local_encoding,
    write_smt_expressions,
)
from utils.util_log import (
    exit_with_error,
    log_info,
    verbose_info,
)
from utils.util_smt import (
    expand_let_expressions_ast_batch,
    expand_ssa_return_in_asserts,
    extract_smt_assertions,
    extract_smt_declarations,
    extract_smt_symbolic_variables,
    extract_ssa_variables,
    extract_symbolic_variables_let_aware,
    match_ssa_definition_variable,
    slice_smt_dependency_closure,
)


class RouterLocalEncodingBuilder:
    """Classify a property slice and build one encoding per router."""

    _LOCAL_ROUTE_KINDS = (
        "CONNECTED_IMPORT",
        "STATIC_IMPORT",
        "BGP_IMPORT",
        "OSPF_IMPORT",
        "CONNECTED_BEST",
        "STATIC_BEST",
        "BGP_BEST",
        "OSPF_BEST",
        "OSPF_Redistributed",
        "OVERALL_BEST",
    )
    _EXPORT_TOKENS = (
        "_BGP_EXPORT",
        "_BGP_SINGLE-EXPORT",
        "_OSPF_EXPORT",
        "_OSPF_SINGLE-EXPORT",
    )
    # Peer exports are dependencies of local imports, not local ownership roots.
    _ROUTE_DEPENDENCY_TOKENS = _EXPORT_TOKENS + (
        "_OSPF_BEST",
        "_OSPF_Redistributed",
    )

    def __init__(
        self,
        routers: Sequence[str],
        output_dir: Path,
        model_igp: bool = False,
        verbose_flag: bool = False,
    ):
        self.routers = tuple(routers)
        self._validate_routers()
        self.output_dir = ensure_directory(Path(output_dir))
        self.model_igp = model_igp
        self.verbose_flag = verbose_flag
        self.state = RouterLocalEncodingState()
        self.last_resolve_dependencies_seconds = 0.0
        self._routers_longest_first = tuple(
            sorted(self.routers, key=lambda router: (-len(router), router))
        )
        self._compile_regex_patterns()

    def _validate_routers(self) -> None:
        """Reject router sets that cannot produce distinct safe output files."""
        if not self.routers:
            raise ValueError("Cannot build router-local encodings without routers")

        duplicates = sorted(
            router
            for router in set(self.routers)
            if self.routers.count(router) > 1
        )
        if duplicates:
            raise ValueError(f"Duplicate router names: {', '.join(duplicates)}")

        invalid = sorted(
            router
            for router in self.routers
            if not router
            or router != router.strip()
            or router in {".", ".."}
            or "/" in router
            or "\\" in router
            or "\x00" in router
        )
        if invalid:
            invalid_names = ", ".join(repr(router) for router in invalid)
            raise ValueError(f"Invalid router names: {invalid_names}")

    def _compile_regex_patterns(self) -> None:
        """Compile ownership and removable-reachability patterns."""
        verbose_info(
            self.verbose_flag,
            "Step 1: Initializing priority templates...",
        )
        remove_templates = [r"reachable_{router}", r"reachable-id_{router}"]
        routers_alt = (
            "(?:"
            + "|".join(map(re.escape, self._routers_longest_first))
            + ")"
        )
        self._remove_patterns = tuple(
            re.compile(template.format(router=routers_alt))
            for template in remove_templates
        )
        local_route_alternatives = "|".join(self._LOCAL_ROUTE_KINDS)
        self._local_route_any = re.compile(
            rf"_(?P<router>{routers_alt})_"
            rf"(?:{local_route_alternatives})"
        )
        self._low_any = re.compile(
            rf"(?:CONTROL-FORWARDING|DATA-FORWARDING)_(?P<router>{routers_alt})"
        )
        self._local_route_any_slice = re.compile(
            rf"0_SLICE-MAIN_(?P<router>{routers_alt})_"
            rf"(?:{local_route_alternatives})"
        )
        self._low_any_slice = re.compile(
            rf"0_SLICE-MAIN_(?:CONTROL-FORWARDING|DATA-FORWARDING)_"
            rf"(?P<router>{routers_alt})"
        )

    def _load_program(
        self,
        declarations: Sequence[str],
        assertions: Sequence[str],
    ) -> None:
        """Reset the builder and load one reduced SMT program."""
        if not declarations:
            raise ValueError("Router-local SMT program has no declarations")
        if not assertions:
            raise ValueError("Router-local SMT program has no assertions")

        self.state = RouterLocalEncodingState()
        for declaration in declarations:
            variables = extract_smt_symbolic_variables(declaration)
            if len(variables) != 1:
                raise ValueError(
                    "Expected one variable in declare-fun expression, "
                    f"found {variables}: {declaration}"
                )
            variable = variables[0]
            if variable in self.state.declarations_by_variable:
                raise ValueError(f"Duplicate SMT declaration for {variable}")
            self.state.declarations_by_variable[variable] = declaration
        self.state.source_assertions.extend(assertions)

    def _build(self) -> None:
        """Run classification, dependency closure, and output generation."""
        self._classify_assertions()
        self._validate_classification()
        self._resolve_dependencies()
        self._validate_resolved_slices()
        self._write_output_files()

    def build_from_expressions(self, sliced_exprs: Sequence[str]) -> None:
        """Build directly from the in-memory global property slice."""
        declarations = []
        assertions = []
        for expr in sliced_exprs:
            stripped = expr.strip()
            if not stripped:
                continue
            if stripped.startswith("(declare-fun"):
                declarations.append(stripped)
            elif stripped.startswith("(assert"):
                assertions.append(stripped)
            elif not stripped.startswith(";"):
                raise ValueError(
                    f"Unsupported expression in router-local SMT program: {stripped}"
                )
        self._load_program(declarations, assertions)
        self._build()

    def _classify_assertions(self) -> None:
        """Classify source assertions by ownership and dependency role."""
        verbose_info(
            self.verbose_flag,
            "Step 2: Classifying assertions...",
        )
        for line in self.state.source_assertions:
            if self._should_remove_assertion(line):
                continue

            is_route_dependency = self._index_route_dependency(line)
            if self._assign_assertion(line) or is_route_dependency:
                continue
            if self._index_supporting_dependencies(line):
                continue
            if self._add_common_assertion(line):
                continue
            self.state.unhandled_assertions.append(line)

        verbose_info(
            self.verbose_flag,
            f"  -> Found {len(self.state.common_assertions)} common assertion(s) "
            "to be added to all files.",
        )

    def _should_remove_assertion(self, line: str) -> bool:
        """Remove global reachability helpers outside the local route model."""
        if self.model_igp:
            if "0_SLICE-MAIN__reachable" in line:
                return True
            if "0_SLICE-" in line and "__reachable" in line:
                return False
        return any(pattern.search(line) for pattern in self._remove_patterns)

    def _assign_assertion(self, line: str) -> bool:
        """Assign an assertion to its router owners when ownership is direct."""
        if self.model_igp:
            assigned_routers = {
                match.group("router")
                for match in self._local_route_any_slice.finditer(line)
            }
            if not assigned_routers and self._has_device_slice_variable(line):
                for router in self.routers:
                    self.state.assertions_by_router[router].add(line)
                return True
            if not assigned_routers:
                assigned_routers = {
                    match.group("router")
                    for match in self._low_any_slice.finditer(line)
                }
        else:
            assigned_routers = {
                match.group("router")
                for match in self._local_route_any.finditer(line)
            }
            if not assigned_routers:
                assigned_routers = {
                    match.group("router")
                    for match in self._low_any.finditer(line)
                }

        assigned_routers = {
            router
            for router in assigned_routers
            if not self._is_bgp_outbound_export_assertion(line, router)
        }

        if assigned_routers:
            for router in assigned_routers:
                self.state.assertions_by_router[router].add(line)
            return True

        return False

    def _has_device_slice_variable(self, line: str) -> bool:
        """Detect model-IGP device slices that must be shared by all routers."""
        for variable in extract_smt_symbolic_variables(line):
            content = variable.strip("|")
            for router in self._routers_longest_first:
                prefix = f"0_SLICE-{router}"
                if content == prefix or content.startswith(prefix):
                    return True
        return False

    def _is_bgp_outbound_export_assertion(self, line: str, router: str) -> bool:
        """Return whether an assertion sends a local BGP route toward a peer."""
        variables = extract_smt_symbolic_variables(line)
        router_prefixes = (
            f"0_{router}_",
            f"0_SLICE-MAIN_{router}_",
        )
        local_variables = [
            variable
            for variable in variables
            if variable.strip("|").startswith(router_prefixes)
        ]
        has_local_export = any(
            "_BGP_EXPORT" in variable for variable in local_variables
        )
        has_local_import = any(
            "_BGP_IMPORT" in variable for variable in local_variables
        )
        return has_local_export and not has_local_import

    def _index_route_dependency(self, line: str) -> bool:
        """Index route producers independently of router ownership."""
        variables = extract_smt_symbolic_variables(line)
        has_bgp_import = any("_BGP_IMPORT" in variable for variable in variables)
        dependency_variables = [
            variable
            for variable in variables
            if any(token in variable for token in self._ROUTE_DEPENDENCY_TOKENS)
        ]
        indexed = False
        for variable in dependency_variables:
            # BGP EXPORT -> IMPORT assertions consume an exported route. They
            # already belong to the receiving router and must not be pulled into
            # another router merely because it references that export record.
            if has_bgp_import and "_BGP_EXPORT" in variable:
                continue
            self.state.route_dependencies[variable].add(line)
            indexed = True
        return indexed

    def _index_supporting_dependencies(self, line: str) -> bool:
        """Index unowned Config, failure, and SSA support assertions."""
        variables = extract_smt_symbolic_variables(line)
        indexed = False
        config_vars = [
            variable for variable in variables if "Config_" in variable
        ]
        failed_vars = [
            variable
            for variable in variables
            if "FAILED-EDGE_" in variable or "FAILED-NODE_" in variable
        ]

        for variable in config_vars:
            self.state.config_dependencies[variable].add(line)
            indexed = True
        for variable in failed_vars:
            self.state.failure_dependencies[variable].add(line)
            indexed = True

        ssa_variable = match_ssa_definition_variable(line)
        if ssa_variable:
            self.state.ssa_dependencies[ssa_variable].add(line)
            indexed = True

        return indexed

    def _add_common_assertion(self, line: str) -> bool:
        """Share assertions that reference the exact source/destination symbols."""
        target_vars = (
            {"|0_SLICE-MAIN_dst-ip|", "|0_SLICE-MAIN_src-ip|"}
            if self.model_igp
            else {"|0_dst-ip|", "|0_src-ip|"}
        )
        vars_in_line = set(extract_symbolic_variables_let_aware(line))
        if vars_in_line.intersection(target_vars):
            self.state.common_assertions.add(line)
            return True
        return False

    def _resolve_ssa_orphans_for_router(
        self,
        router: str,
        ssa_owners: Dict[str, Set[str]],
    ) -> None:
        """Assign SSA definitions reachable only through another SSA symbol."""
        for ssa_var, lines in self.state.ssa_dependencies.items():
            if lines.issubset(self.state.assertions_by_router[router]):
                continue
            for line in lines:
                if line in self.state.assertions_by_router[router]:
                    continue
                deps = extract_ssa_variables(line, exclude=ssa_var)
                if not deps:
                    continue
                target_routers: Set[str] = set()
                for dep in deps:
                    target_routers.update(ssa_owners.get(dep, set()))
                if router in target_routers:
                    self.state.assertions_by_router[router].add(line)

    def _resolve_dependencies(self) -> None:
        """Resolve dependencies until ownership reaches a global fixed point."""
        started_at = time.time()
        verbose_info(self.verbose_flag, "Step 3: Resolving dependencies...")
        variable_cache: Dict[str, Set[str]] = {}
        pass_index = 0

        while True:
            pass_index += 1
            initial_size = sum(
                len(assertions)
                for assertions in self.state.assertions_by_router.values()
            )
            verbose_info(
                self.verbose_flag,
                f"  -> Dependency resolution pass {pass_index}...",
            )
            for router in self.routers:
                self._resolve_router_dependencies(router, variable_cache)
            final_size = sum(
                len(assertions)
                for assertions in self.state.assertions_by_router.values()
            )
            if final_size == initial_size:
                break
        self.last_resolve_dependencies_seconds = time.time() - started_at

    @staticmethod
    def _variables_in_assertion(
        assertion: str,
        cache: Dict[str, Set[str]],
    ) -> Set[str]:
        variables = cache.get(assertion)
        if variables is None:
            variables = set(extract_symbolic_variables_let_aware(assertion))
            cache[assertion] = variables
        return variables

    def _referenced_variables(
        self,
        router: str,
        cache: Dict[str, Set[str]],
    ) -> Set[str]:
        variables = set()
        for assertion in self.state.assertions_by_router[router]:
            variables.update(self._variables_in_assertion(assertion, cache))
        return variables

    def _ssa_owners(
        self,
        cache: Dict[str, Set[str]],
    ) -> Dict[str, Set[str]]:
        owners: Dict[str, Set[str]] = defaultdict(set)
        for router in self.routers:
            for assertion in self.state.assertions_by_router[router]:
                for variable in self._variables_in_assertion(assertion, cache):
                    if variable.startswith("SSA_"):
                        owners[variable].add(router)
        return owners

    def _add_variable_dependencies(
        self,
        router: str,
        referenced_variables: Set[str],
    ) -> None:
        assertions = self.state.assertions_by_router[router]
        dependency_indexes = (
            self.state.route_dependencies,
            self.state.config_dependencies,
            self.state.failure_dependencies,
            self.state.ssa_dependencies,
        )
        for variable in referenced_variables:
            for dependency_index in dependency_indexes:
                assertions.update(dependency_index.get(variable, set()))

    def _resolve_router_dependencies(
        self,
        router: str,
        variable_cache: Dict[str, Set[str]],
    ) -> None:
        while True:
            assertions = self.state.assertions_by_router[router]
            initial_size = len(assertions)
            self._add_variable_dependencies(
                router,
                self._referenced_variables(router, variable_cache),
            )
            self._resolve_ssa_orphans_for_router(
                router,
                self._ssa_owners(variable_cache),
            )
            if len(assertions) == initial_size:
                return

    def _validate_resolved_slices(self) -> None:
        """Require every router slice to contain its final local best route."""
        missing_local_best = []
        for router in self.routers:
            prefixes = (
                f"0_{router}_OVERALL_BEST_",
                f"0_SLICE-MAIN_{router}_OVERALL_BEST_",
            )
            variables = {
                variable.strip("|")
                for assertion in self._final_assertions(router)
                for variable in extract_smt_symbolic_variables(assertion)
            }
            if not any(
                variable.startswith(prefixes) for variable in variables
            ):
                missing_local_best.append(router)

        if missing_local_best:
            raise ValueError(
                "Router-local slices contain no local OVERALL_BEST route for: "
                + ", ".join(missing_local_best)
            )

    def _write_output_files(self) -> None:
        """Assemble and persist the final SMT encoding for each router."""
        verbose_info(
            self.verbose_flag,
            "Step 4: Assembling and writing final files...",
        )
        programs = {}
        for router in self.routers:
            final_asserts = self._final_assertions(router)
            final_declarations = self._required_declarations(final_asserts)
            programs[router] = (final_declarations, final_asserts)

        for router in self.routers:
            final_declarations, final_asserts = programs[router]
            write_router_local_encoding(
                self.output_dir,
                router,
                final_declarations,
                final_asserts,
            )
            updated_fragments = update_router_assume_guarantee_declarations(
                self.output_dir.parent,
                router,
                self.state.declarations_by_variable,
            )
            verbose_info(
                self.verbose_flag,
                "  -> Wrote file for '%s' with %s declarations and %s asserts.",
                router,
                len(final_declarations),
                len(final_asserts),
            )
            if updated_fragments:
                verbose_info(
                    self.verbose_flag,
                    "  -> Added external declarations to %s assume-guarantee "
                    "file(s).",
                    updated_fragments,
                )

    def _final_assertions(self, router: str) -> List[str]:
        return sorted(
            self.state.assertions_by_router[router]
            | self.state.common_assertions
        )

    def _required_declarations(
        self,
        assertions: Sequence[str],
    ) -> List[str]:
        variables = {
            variable
            for assertion in assertions
            for variable in extract_symbolic_variables_let_aware(assertion)
        }
        missing_variables = sorted(
            variables - self.state.declarations_by_variable.keys()
        )
        if missing_variables:
            raise ValueError(
                "Router-local assertions reference variables without declarations: "
                + ", ".join(missing_variables[:10])
            )
        return sorted(
            self.state.declarations_by_variable[variable]
            for variable in variables
        )

    def _validate_classification(self) -> None:
        """Reject assertions outside the supported ownership model."""
        if not self.state.unhandled_assertions:
            return
        examples = "\n".join(
            f"  - {line}" for line in self.state.unhandled_assertions[:5]
        )
        raise ValueError(
            f"Found {len(self.state.unhandled_assertions)} unclassified "
            f"router-local assertion(s):\n{examples}"
        )

    def build_from_file(self, input_file: Path) -> None:
        """Build from a persisted global property slice."""
        self.build_from_expressions(load_smt_source_lines(Path(input_file)))


def build_property_smt_slice(
    smt_encoding_path: Path,
    target_variables_path: Path,
    output_path: Path,
    verbose_flag: bool = False,
) -> List[str]:
    """Build the global dependency slice rooted at property variables."""
    smt_lines = load_smt_source_lines(smt_encoding_path)
    declarations = extract_smt_declarations(smt_lines)
    assertions = extract_smt_assertions(smt_lines)
    try:
        assertions, ssa_return_names = _expand_global_assertions(
            assertions, verbose_flag
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to expand let expressions in {smt_encoding_path}: {exc}"
        ) from exc
    declarations = _remove_ssa_return_declarations(
        declarations, ssa_return_names
    )
    target_variables = load_target_smt_variables(target_variables_path)
    sliced_expressions = slice_smt_dependency_closure(
        declarations,
        assertions,
        target_variables,
    )
    write_smt_expressions(output_path, sliced_expressions)
    verbose_info(
        verbose_flag,
        f"Sliced SMT encoding written to {output_path}.",
    )
    return sliced_expressions


def _expand_global_assertions(
    assertions: List[str],
    verbose_flag: bool,
) -> Tuple[List[str], Set[str]]:
    started_at = time.time()
    expanded = expand_let_expressions_ast_batch(assertions)
    verbose_info(
        verbose_flag,
        "Expanded let expressions using AST-based substitution (took %.2fs)",
        time.time() - started_at,
    )
    return expand_ssa_return_in_asserts(expanded)


def _remove_ssa_return_declarations(
    declarations: List[str],
    ssa_return_names: Set[str],
) -> List[str]:
    if not ssa_return_names:
        return declarations
    retained = []
    for declaration in declarations:
        variables = extract_smt_symbolic_variables(declaration)
        if not variables or variables[0] not in ssa_return_names:
            retained.append(declaration)
    return retained


def build_router_local_encodings(
    work_dir: Path,
    sliced_expressions: Optional[Sequence[str]] = None,
    verbose_flag: bool = False,
) -> Dict[str, float]:
    """Build one dependency-resolved SMT encoding per router."""
    validate_router_local_encoding_outputs(work_dir)
    routers = load_hostnames(work_dir)
    model_igp = load_optional_model_igp(work_dir)
    output_dir = ensure_directory(work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR)
    global_slice = output_dir / util_keyword.GLOBAL_ENCODING_FILE

    verbose_info(
        verbose_flag,
        f"\nStarting router-local encoding for {len(routers)} routers...",
    )
    builder = RouterLocalEncodingBuilder(
        routers=routers,
        output_dir=output_dir,
        model_igp=model_igp,
        verbose_flag=verbose_flag,
    )
    if sliced_expressions is not None:
        builder.build_from_expressions(sliced_expressions)
    else:
        builder.build_from_file(global_slice)
    verbose_info(
        verbose_flag,
        f"Router-local encoding completed. Files saved in '{output_dir}'."
    )
    return {
        "resolve_dependencies_seconds": builder.last_resolve_dependencies_seconds
    }


def _parse_cli_args(
    args: Sequence[str],
) -> Tuple[bool, bool, Optional[str]]:
    verbose_flag = False
    delete_flag = False
    work_dir = None
    for argument in args:
        if argument == "-v":
            verbose_flag = True
        elif argument == "-d":
            delete_flag = True
        elif argument.startswith("-"):
            raise ValueError(f"Unknown option: {argument}")
        elif work_dir is not None:
            raise ValueError("Multiple work directories specified")
        else:
            work_dir = argument
    return verbose_flag, delete_flag, work_dir


def _print_usage() -> None:
    print("Usage: python 2_router_local_encoding.py [-v] [-d] <work_directory>")
    print("Options:")
    print("  -v     Verbose mode: Show detailed INFO logs")
    print("         Without -v: Only show WARNING/ERROR logs and completion status")
    print("  -d     Delete intermediate output files before running, then exit")
    print("  -h, --help      Show this help message")
    print("")
    print("Example: python 2_router_local_encoding.py smt_output_0001")
    print("         python 2_router_local_encoding.py -v smt_output_0001")
    print("         python 2_router_local_encoding.py -d smt_output_0001")


def _delete_outputs(work_dir: Path) -> None:
    """Delete files produced by stage 2 and report the result."""
    deleted_paths = delete_router_local_encoding_outputs(work_dir)
    if not deleted_paths:
        log_info("No intermediate files found to delete.")
        return
    for deleted_path in deleted_paths:
        log_info("Deleted intermediate output: %s", deleted_path)


def _run_router_local_encoding(work_dir: Path, verbose_flag: bool) -> None:
    """Validate inputs and build the global and router-local SMT encoding slices."""
    validate_router_local_encoding_inputs(work_dir)
    clear_router_local_encoding_files(work_dir)
    output_dir = ensure_directory(work_dir / util_keyword.ROUTER_LOCAL_ENCODING_DIR)
    global_slice = output_dir / util_keyword.GLOBAL_ENCODING_FILE

    verbose_info(verbose_flag, "Step 1: Global SMT encoding slicing...")
    sliced_expressions = build_property_smt_slice(
        work_dir / util_keyword.SMT_ENCODING_FILE,
        work_dir / util_keyword.PROPERTY_VARIABLES_FILE,
        global_slice,
        verbose_flag=verbose_flag,
    )

    verbose_info(verbose_flag, "\nStep 2: Router-local encoding...")
    build_router_local_encodings(
        work_dir,
        sliced_expressions,
        verbose_flag=verbose_flag,
    )


def main(args: Optional[Sequence[str]] = None) -> None:
    """Run the stage-2 router-local encoding pipeline."""
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
            f"Work directory does not exist or is not a directory: "
            f"{work_dir_path}"
        )

    if delete_flag:
        _delete_outputs(work_dir_path)
        return

    try:
        _run_router_local_encoding(work_dir_path, verbose_flag)
    except Exception as error:
        exit_with_error(f"Error: {error}")

    if not verbose_flag:
        print("[✓] Completed: Router-Local Slice Encoding")


if __name__ == "__main__":
    main()
