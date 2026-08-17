#!/usr/bin/env python3
"""Construct, parse, transform, and solve SMT2 encodings.

This module owns SMT text/AST operations and the common Z3 execution boundary;
it does not read or write project files.
"""

import ipaddress
import re
import subprocess
from array import array
from collections import deque
from pathlib import Path
from typing import (
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from utils import util_keyword
from utils.util_data import (
    ControlForwardingState,
    RouteAssumptionCase,
    RouteAttributes,
    SmtConstraint,
)
from utils.util_log import get_logger

logger = get_logger(__name__)

_COMMUNITY_OVERALL_OR_KEY = "_overall_or_constraint"
_COMMUNITY_OVERALL_AND_KEY = "_overall_and_constraint"
_COMBINED_COMMUNITY_KEYS = frozenset(
    {_COMMUNITY_OVERALL_OR_KEY, _COMMUNITY_OVERALL_AND_KEY}
)
_INTERNET2_EXPORT_ENV_ASSUME_MARKER = (
    "; Assume: disable all external BGP route inputs to"
)

# SMT2 keywords that should not be treated as symbolic variables
_SMT2_KEYWORDS = {
    'assert', 'declare-fun', 'define-fun', 'check-sat', 'set-option',
    'not', 'and', 'or', 'ite', 'let',
    '<', '<=', '>', '>=', '=', '=>', '+', '-', '*', 'div', 'mod',
    'bvnot', 'bvor', 'bvand', 'bvule', 'bvult', 'extract',
    'true', 'false',
    'Bool', 'Int', 'BitVec', '_'
}
_RE_BIN_CONST = re.compile(r'#b[0-1]+$')
_RE_HEX_CONST = re.compile(r'#[xX][0-9a-fA-F]+$')
_RE_DEC_CONST = re.compile(r'\d+$')
_SSA_DEFINITION_ASSERT_RE = re.compile(r"^\(assert \(= (SSA_[A-Z]+\d+) ")
_SSA_VARIABLE_RE = re.compile(r"\b(SSA_[A-Z]+\d+)\b")
_CONFIG_EQUALITY_ASSERT_RE = re.compile(
    r"^;?\s*\(assert \(= (Config_\S+) (\S+)\)\)"
)

_ROUTE_ATTRIBUTE_FIELDS = (
    (util_keyword.ATTR_ADMIN_DIST, "admin_dist"),
    (util_keyword.ATTR_LOCAL_PREF, "local_pref"),
    (util_keyword.ATTR_METRIC, "metric"),
    (util_keyword.ATTR_MED, "med"),
    (util_keyword.ATTR_OSPF_AREA, "ospf_area"),
    (util_keyword.ATTR_OSPF_TYPE, "ospf_type"),
    (util_keyword.ATTR_HISTORY, "history"),
)


def _combine_smt_expressions(
    expressions: Sequence[str],
    operator: str,
    empty_value: str,
) -> str:
    if not expressions:
        return empty_value
    if len(expressions) == 1:
        return expressions[0]
    return f"({operator} {' '.join(expressions)})"


def _route_attribute_values(
    attributes: RouteAttributes,
) -> Iterable[Tuple[str, object]]:
    for attribute, field_name in _ROUTE_ATTRIBUTE_FIELDS:
        value = getattr(attributes, field_name)
        if value is not None:
            yield attribute, value


def parse_config_equality_assertion(line: str) -> Optional[Tuple[str, str]]:
    """Parse a simple active or commented ``Config_*`` equality assertion."""
    match = _CONFIG_EQUALITY_ASSERT_RE.search(line.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def negate_smt_expression(expression: str) -> str:
    """Wrap one SMT expression in ``not``."""
    return f"(not {expression.strip()})"


# Router-level variable naming and constraint construction.

class SmtVariableNamer:
    """Centralize SMT identifier escaping and project naming conventions."""

    def __init__(self, variable_prefix: str):
        self.variable_prefix = variable_prefix

    @staticmethod
    def escape_inner(inner: str) -> str:
        return inner.replace("|", "\\|")

    def name(self, inner: str) -> str:
        return f"|{self.escape_inner(inner)}|"

    def overall_best(self, router: str, attribute: str) -> str:
        suffix = (
            f"_{util_keyword.SMT_OVERALL_BEST_TOKEN}_None_{attribute}"
        )
        return self.name(f"{self.variable_prefix}{router}{suffix}")

    def control_forwarding(self, router: str, interface: str) -> str:
        return self.name(
            f"{self.variable_prefix}{util_keyword.SMT_CONTROL_FORWARDING_TOKEN}_"
            f"{router}_{interface}"
        )


class SmtConstraintBuilder:
    """Convert typed analysis models into SMT constraints without file I/O."""

    def __init__(self, namer: SmtVariableNamer):
        self.namer = namer

    @staticmethod
    def _literal(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str) and re.fullmatch(r"0b[01]+", value):
            return f"#b{value[2:]}"
        return str(value)

    def _equality(self, variable: str, value) -> SmtConstraint:
        return SmtConstraint(f"(= {variable} {self._literal(value)})")

    def normal_route_constraints(
        self,
        router: str,
        attributes: RouteAttributes,
    ) -> Tuple[SmtConstraint, ...]:
        constraints = []
        if attributes.permitted is not None:
            constraints.append(
                self._equality(
                    self.namer.overall_best(
                        router, util_keyword.ATTR_PERMITTED
                    ),
                    attributes.permitted,
                )
            )
        if attributes.prefix_length is not None:
            constraints.append(
                self._equality(
                    self.namer.overall_best(
                        router, util_keyword.ATTR_PREFIX_LENGTH
                    ),
                    attributes.prefix_length,
                )
            )
        for attribute, value in _route_attribute_values(attributes):
            constraints.append(
                self._equality(
                    self.namer.overall_best(router, attribute),
                    value,
                )
            )

        for variable, value in attributes.communities.items():
            if variable in _COMBINED_COMMUNITY_KEYS:
                continue
            if "(or (= " in value:
                constraints.append(SmtConstraint(value))
            else:
                constraints.append(self._equality(variable, value))

        for key in (
            _COMMUNITY_OVERALL_OR_KEY,
            _COMMUNITY_OVERALL_AND_KEY,
        ):
            if key in attributes.communities:
                constraints.append(SmtConstraint(attributes.communities[key]))
        return tuple(constraints)

    def negated_route_constraints(
        self,
        router: str,
        attributes: RouteAttributes,
    ) -> Tuple[SmtConstraint, ...]:
        mismatches: List[str] = []
        if attributes.prefix_length is not None:
            mismatches.append(
                self._mismatch(
                    router,
                    util_keyword.ATTR_PREFIX_LENGTH,
                    attributes.prefix_length,
                )
            )

        if attributes.permitted is not None:
            mismatches.append(
                self._mismatch(
                    router,
                    util_keyword.ATTR_PERMITTED,
                    attributes.permitted,
                )
            )
        for attribute, value in _route_attribute_values(attributes):
            mismatches.append(self._mismatch(router, attribute, value))
        if attributes.negated_community_constraint:
            mismatches.append(attributes.negated_community_constraint)

        expression = _combine_smt_expressions(mismatches, "or", "")
        if not expression:
            return ()
        return (SmtConstraint(expression),)

    def _mismatch(self, router: str, attribute: str, value) -> str:
        variable = self.namer.overall_best(router, attribute)
        return f"(not (= {variable} {self._literal(value)}))"

    def normal_control_constraints(
        self,
        router: str,
        state: ControlForwardingState,
    ) -> Tuple[SmtConstraint, ...]:
        return tuple(
            self._equality(
                self.namer.control_forwarding(router, interface),
                interface in state.active_interfaces,
            )
            for interface in state.considered_interfaces
        )

    def negated_control_constraints(
        self,
        router: str,
        state: ControlForwardingState,
    ) -> Tuple[SmtConstraint, ...]:
        violations = [
            self._mismatch_control(
                router,
                interface,
                interface in state.active_interfaces,
            )
            for interface in state.considered_interfaces
        ]
        expression = _combine_smt_expressions(violations, "or", "")
        if not expression:
            return ()
        return (SmtConstraint(expression),)

    def _mismatch_control(
        self,
        router: str,
        interface: str,
        active: bool,
    ) -> str:
        variable = self.namer.control_forwarding(router, interface)
        return f"(not (= {variable} {self._literal(active)}))"

    def prefix_length_bounds(
        self,
        router: str,
        maximum: int,
    ) -> Tuple[SmtConstraint, ...]:
        variable = self.namer.overall_best(
            router,
            util_keyword.ATTR_PREFIX_LENGTH,
        )
        return (
            SmtConstraint(f"(<= {variable} {maximum})"),
            SmtConstraint(f"(>= {variable} 0)"),
        )


# SMT extraction and dependency slicing.

def extract_smt_declarations(lines: List[str]) -> List[str]:
    """Extract complete ``declare-fun`` expressions from SMT-LIB lines."""
    return _extract_parenthesized_expressions(lines, "declare-fun")


def extract_smt_assertions(lines: List[str]) -> List[str]:
    """Extract complete ``assert`` expressions from SMT-LIB lines."""
    return _extract_parenthesized_expressions(lines, "assert")


def _extract_parenthesized_expressions(
    lines: List[str],
    expression_type: str,
) -> List[str]:
    expressions = []
    current_expression = ""
    depth = 0
    in_expression = False
    start_line_number: Optional[int] = None
    marker = f"({expression_type}"

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if not in_expression and line.startswith(marker):
            in_expression = True
            start_line_number = line_number
        if not in_expression:
            continue

        current_expression += " " + line
        depth += line.count("(") - line.count(")")
        if depth < 0:
            raise ValueError(
                f"Unexpected ')' in {expression_type} expression at line "
                f"{line_number}"
            )
        if depth != 0:
            continue

        expression = current_expression.strip()
        if expression.startswith(marker):
            expressions.append(expression)
        current_expression = ""
        in_expression = False
        start_line_number = None

    if in_expression:
        raise ValueError(
            f"Unterminated {expression_type} expression starting at line "
            f"{start_line_number}"
        )

    return expressions


def extract_smt_symbolic_variables(expression: str) -> List[str]:
    """Extract symbolic atoms using the stage-2 fast tokenizer semantics."""
    return [
        token
        for token in _tokenize_smt_symbols(expression)
        if is_symbolic_atom(token)
    ]


def _tokenize_smt_symbols(expression: str) -> List[str]:
    """Tokenize SMT symbols while omitting parentheses."""
    tokens = []
    index = 0
    while index < len(expression):
        character = expression[index]
        if character.isspace() or character in "()":
            index += 1
            continue
        if character == "|":
            start = index
            index += 1
            while index < len(expression):
                if expression[index] == "|" and (
                    index == start + 1 or expression[index - 1] != "\\"
                ):
                    index += 1
                    break
                if (
                    expression[index] == "\\"
                    and index + 1 < len(expression)
                    and expression[index + 1] == "|"
                ):
                    index += 2
                else:
                    index += 1
            tokens.append(expression[start:index])
            continue

        start = index
        while (
            index < len(expression)
            and not expression[index].isspace()
            and expression[index] not in "()"
        ):
            index += 1
        tokens.append(expression[start:index])
    return tokens


def slice_smt_dependency_closure(
    declarations: List[str],
    assertions: List[str],
    target_variables: Set[str],
) -> List[str]:
    """Compute the SMT declaration/assertion closure of target variables."""
    variable_ids: Dict[str, int] = {}

    def variable_id(variable: str) -> int:
        existing = variable_ids.get(variable)
        if existing is not None:
            return existing
        identifier = len(variable_ids)
        variable_ids[variable] = identifier
        return identifier

    declaration_by_variable: List[int] = []
    declared_variables: Dict[str, int] = {}
    assertion_variables: List[List[int]] = [[] for _ in assertions]
    assertions_by_variable: Dict[int, array] = {}

    for declaration_index, declaration in enumerate(declarations):
        variables = extract_smt_symbolic_variables(declaration)
        if len(variables) != 1:
            raise ValueError(
                "Expected one variable in declare-fun expression, "
                f"found {variables}: {declaration}"
            )
        variable = variables[0]
        if variable in declared_variables:
            raise ValueError(f"Duplicate SMT declaration for {variable}")
        declared_variables[variable] = declaration_index
        identifier = variable_id(variable)
        if identifier >= len(declaration_by_variable):
            declaration_by_variable.extend(
                [-1] * (identifier - len(declaration_by_variable) + 1)
            )
        declaration_by_variable[identifier] = declaration_index

    for assertion_index, assertion in enumerate(assertions):
        seen_identifiers = set()
        local_identifiers = []
        for variable in extract_symbolic_variables_let_aware(assertion):
            identifier = variable_id(variable)
            if identifier in seen_identifiers:
                continue
            seen_identifiers.add(identifier)
            local_identifiers.append(identifier)
            assertions_by_variable.setdefault(identifier, array("I")).append(
                assertion_index
            )
        assertion_variables[assertion_index] = local_identifiers

    missing_targets = sorted(target_variables - declared_variables.keys())
    if missing_targets:
        raise ValueError(
            "Target SMT variables have no declarations: "
            + ", ".join(missing_targets[:10])
        )

    selected_declarations = bytearray(len(declarations))
    selected_declaration_ids = []
    selected_assertions = bytearray(len(assertions))
    selected_assertion_ids = []
    visited_variables = set()
    pending_variables = deque()

    for variable in target_variables:
        identifier = variable_ids.get(variable)
        if identifier is None:
            raise ValueError(f"Target SMT variable was not indexed: {variable}")
        if identifier not in visited_variables:
            visited_variables.add(identifier)
            pending_variables.append(identifier)

    while pending_variables:
        identifier = pending_variables.popleft()
        if (
            identifier >= len(declaration_by_variable)
            or declaration_by_variable[identifier] == -1
        ):
            raise ValueError(
                f"SMT variable id {identifier} has no declare-fun expression"
            )

        declaration_index = declaration_by_variable[identifier]
        if not selected_declarations[declaration_index]:
            selected_declarations[declaration_index] = 1
            selected_declaration_ids.append(declaration_index)

        for assertion_index in assertions_by_variable.get(identifier, ()):
            if selected_assertions[assertion_index]:
                continue
            selected_assertions[assertion_index] = 1
            selected_assertion_ids.append(assertion_index)
            for related_identifier in assertion_variables[assertion_index]:
                if related_identifier not in visited_variables:
                    visited_variables.add(related_identifier)
                    pending_variables.append(related_identifier)

    identifier_to_variable: List[Optional[str]] = [None] * len(variable_ids)
    for variable, identifier in variable_ids.items():
        identifier_to_variable[identifier] = variable
    missing_declarations = []
    for assertion_index in selected_assertion_ids:
        for identifier in assertion_variables[assertion_index]:
            if (
                identifier >= len(declaration_by_variable)
                or declaration_by_variable[identifier] == -1
            ):
                variable = identifier_to_variable[identifier]
                if variable is not None:
                    missing_declarations.append(variable)
    if missing_declarations:
        sample = ", ".join(missing_declarations[:10])
        raise ValueError(
            "Selected SMT assertions reference variables without declarations: "
            + sample
        )

    selected_declaration_ids.sort()
    selected_assertion_ids.sort()
    return [declarations[index] for index in selected_declaration_ids] + [
        assertions[index] for index in selected_assertion_ids
    ]


def extract_constraint_variables(constraints: str) -> Set[str]:
    """Extract quoted SMT identifiers and unquoted ``Config_*`` variables."""
    pattern = r"(\|[^|]+\||Config_[^\s()]+)"
    return set(re.findall(pattern, constraints))


def match_ssa_definition_variable(assertion: str) -> Optional[str]:
    """Return the SSA variable defined by an equality assertion, if present."""
    match = _SSA_DEFINITION_ASSERT_RE.match(assertion)
    return match.group(1) if match else None


def extract_ssa_variables(
    expression: str,
    exclude: Optional[str] = None,
) -> Set[str]:
    """Return ``SSA_*`` variables mentioned in an SMT expression."""
    return {
        variable
        for variable in _SSA_VARIABLE_RE.findall(expression)
        if variable != exclude
    }


def extract_smt_declaration_map(smt_content: str) -> Dict[str, str]:
    """Map variables to complete ``declare-fun`` expressions."""
    declarations = {}
    pattern = r"\(declare-fun\s+(\|[^|]+\||[^\s()]+)\s+\(\)\s+([^)]+)\)"
    for variable, variable_type in re.findall(
        pattern,
        smt_content,
        re.MULTILINE | re.DOTALL,
    ):
        declarations[variable] = (
            f"(declare-fun {variable} () {variable_type.strip()})"
        )

    lines = smt_content.splitlines()
    line_index = 0
    while line_index < len(lines):
        line = lines[line_index].strip()
        if not line.startswith("(declare-fun"):
            line_index += 1
            continue

        declaration_parts = [line]
        depth = line.count("(") - line.count(")")
        next_index = line_index + 1
        while next_index < len(lines) and depth > 0:
            next_line = lines[next_index]
            declaration_parts.append(next_line)
            depth += next_line.count("(") - next_line.count(")")
            next_index += 1
        declaration = " ".join(declaration_parts)
        variable_match = re.search(
            r"\(declare-fun\s+(\|[^|]+\||[^\s()]+)",
            declaration,
        )
        if variable_match:
            declarations[variable_match.group(1)] = declaration.strip()
        line_index = next_index
    return declarations


_EXTERNAL_DECLARATIONS_HEADER = (
    "; SMT variables absent from the router-local encoding"
)
_SMT_SECTION_BORDER = "; " + "*" * 68
_INTERNET2_MODEL_REFINEMENT_NOTE = (
    "; NOTE: Route constraints were refined from a Z3 model, not parsed "
    "from simulation output."
)


def add_assume_guarantee_declarations(
    assume_guarantee: str,
    local_encoding: str,
    available_declarations: Dict[str, str],
) -> str:
    """Prepend declarations referenced outside the router-local encoding."""
    body = assume_guarantee.strip()
    if body.startswith(_EXTERNAL_DECLARATIONS_HEADER):
        _, separator, body = body.partition("\n\n")
        if not separator:
            body = ""
    known_declarations = dict(extract_smt_declaration_map(assume_guarantee))
    known_declarations.update(available_declarations)
    referenced_variables = extract_constraint_variables(body)
    local_variables = set(extract_smt_declaration_map(local_encoding))
    missing_variables = sorted(referenced_variables - local_variables)
    unresolved_variables = [
        variable
        for variable in missing_variables
        if variable not in known_declarations
    ]
    if unresolved_variables:
        raise ValueError(
            "Missing SMT declarations for assume-guarantee variables: "
            + ", ".join(unresolved_variables)
        )
    if not missing_variables:
        return f"{body}\n"

    declarations = "\n".join(
        known_declarations[variable] for variable in missing_variables
    )
    return (
        f"{_EXTERNAL_DECLARATIONS_HEADER}\n"
        f"{declarations}\n\n{body}\n"
    )


def mark_internet2_model_refinement(content: str) -> str:
    """Mark an assume-guarantee whose route values came from a Z3 model."""
    if _INTERNET2_MODEL_REFINEMENT_NOTE in content:
        return content

    stripped = content.strip()
    if stripped.startswith(_EXTERNAL_DECLARATIONS_HEADER):
        declarations, separator, body = stripped.partition("\n\n")
        if separator:
            return (
                f"{declarations}\n\n{_INTERNET2_MODEL_REFINEMENT_NOTE}\n"
                f"{body}\n"
            )
    return f"{_INTERNET2_MODEL_REFINEMENT_NOTE}\n{stripped}\n"


def _render_smt_section(title: str, contents: Sequence[str]) -> str:
    """Render one non-empty assume-guarantee section."""
    blocks = [content.strip() for content in contents if content.strip()]
    if not blocks:
        return ""
    return (
        f"{_SMT_SECTION_BORDER}\n"
        f"; {title}\n"
        f"{_SMT_SECTION_BORDER}\n\n"
        + "\n\n".join(blocks)
    )


def build_peer_route_assumption_constraints(
    router: str,
    peer: str,
    control_variables: Sequence[str],
    route_cases: Sequence[RouteAssumptionCase],
    control_constraints: Sequence[SmtConstraint],
) -> str:
    """Couple each peer route alternative with its boundary decisions."""
    assignments = {}
    equality_pattern = re.compile(
        r"^\(=\s+(\|[^|]+\|)\s+(true|false)\)$"
    )
    for constraint in control_constraints:
        match = equality_pattern.fullmatch(constraint.expression.strip())
        if match:
            assignments[match.group(1)] = match.group(2)

    case_expressions = []
    loop_prevention_comments = []
    for case_index, route_case in enumerate(route_cases, 1):
        expressions = [
            constraint.expression
            for constraint in route_case.route_constraints
        ]
        for variable in control_variables:
            value = assignments.get(variable)
            if value is None:
                continue
            if value == "false" and router in route_case.route_origins:
                value = "true"
                loop_prevention_comments.append(
                    f"; BGP loop prevention in route case {case_index}: "
                    f"force peer {peer} to forward toward the route origin"
                )
            expressions.append(f"(= {variable} {value})")
        case_expressions.append(f"(and {' '.join(expressions)})")

    if not case_expressions:
        raise ValueError(f"No route assumption cases for peer '{peer}'")
    expression = case_expressions[0]
    if len(case_expressions) > 1:
        expression = f"(or {' '.join(case_expressions)})"
    blocks = [*loop_prevention_comments, f"(assert {expression})"]
    return "\n".join(blocks)


def build_satisfaction_assume_guarantee_constraints(
    peer_route_assumptions: List[Tuple[str, str]],
    own_route_attributes: str,
    normal_stable_states: str,
) -> str:
    """Assume peer behavior and require the expected local behavior."""
    peer_routes = [
        f"; Peer: {neighbor}\n{attributes.strip()}"
        for neighbor, attributes in peer_route_assumptions
        if attributes.strip()
    ]
    sections = [
        "; Satisfaction assume-guarantee",
        "; Boundary control-forwarding decisions are coupled with peer route cases",
        _render_smt_section("Assume: Peer Best Routes", peer_routes),
        _render_smt_section(
            "Guarantee: Local Best Route & Local Control-Forwarding Decisions",
            [own_route_attributes, normal_stable_states],
        ),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def build_violation_assume_guarantee_constraints(
    peer_route_assumptions: List[Tuple[str, str]],
    combined_negated_constraint: str,
) -> str:
    """Assume peer behavior and require a violation of local behavior."""
    peer_routes = [
        f"; Peer: {neighbor}\n{attributes.strip()}"
        for neighbor, attributes in peer_route_assumptions
        if attributes.strip()
    ]
    sections = [
        "; Violation assume-guarantee",
        "; Boundary control-forwarding decisions are coupled with peer route cases",
        _render_smt_section("Assume: Peer Best Routes", peer_routes),
        _render_smt_section(
            "Guarantee: Local Best Route & Local Control-Forwarding Decisions",
            [combined_negated_constraint],
        ),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def build_consistency_smt(base_smt: str, assume_guarantee: str) -> str:
    """Append a stage-1 assume-guarantee fragment to a sliced SMT encoding."""
    return (
        f"{base_smt.rstrip()}\n\n{assume_guarantee.rstrip()}\n\n"
        f"{util_keyword.SMT_CHECK_SAT}\n"
    )


def run_z3_text(
    smt_content: str,
    *,
    executable: str = util_keyword.Z3,
    arguments: Sequence[str] = ("-smt2", "-in"),
):
    """Run Z3 with SMT text on stdin and return its completed process."""
    return subprocess.run(
        [executable, *arguments],
        input=smt_content,
        capture_output=True,
        text=True,
        check=False,
    )


def require_successful_z3_output(result, context: str) -> str:
    """Return Z3 stdout or raise with process and SMT error details."""
    output = result.stdout.strip()
    errors = []
    if result.returncode != 0:
        errors.append(f"exit code {result.returncode}")
    if result.stderr.strip():
        errors.append(f"stderr: {result.stderr.strip()}")
    error_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("(error")
    ]
    if error_lines:
        errors.append("; ".join(error_lines))
    if not output:
        errors.append("empty output")
    if errors:
        raise RuntimeError(f"Z3 failed for {context}: {' | '.join(errors)}")
    return output


def run_z3_file(
    smt_path: Union[str, Path],
    *,
    executable: str = util_keyword.Z3,
):
    """Run Z3 for one SMT2 file and return its completed process."""
    return subprocess.run(
        [executable, str(smt_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def check_smt_satisfiability(smt_content: str) -> Tuple[bool, str]:
    """Run Z3 on SMT text and return ``(is_sat, diagnostic)``."""
    try:
        result = run_z3_text(smt_content)
    except FileNotFoundError:
        return False, "Z3 not found in PATH"
    except OSError as exc:
        return False, f"Error running Z3: {exc}"

    output = result.stdout.strip()
    if result.stderr.strip():
        logger.warning(f"Z3 stderr: {result.stderr.strip()}")
    if result.returncode != 0:
        logger.warning(f"Z3 return code: {result.returncode}")

    if "(error" in output:
        error_lines = [
            line for line in output.splitlines() if line.startswith("(error")
        ]
        error_message = "; ".join(error_lines)
        if "unknown constant" not in error_message:
            return False, f"Z3 error: {error_message}"

        logger.warning(f"Compatibility issue detected: {error_message}")
        for line in reversed(output.splitlines()):
            status = line.strip()
            if not status or status.startswith("(error"):
                continue
            if status == "sat":
                return True, "sat (compatibility mode)"
            if status == "unsat":
                return False, "unsat (compatibility mode)"
            break
        return False, f"Z3 error: {error_message}"

    if output == "sat":
        return True, output
    if output == "unsat":
        return False, output
    logger.warning(f"Unexpected Z3 output: {output}")
    return False, f"Unexpected output: {output}"


# SMT S-expression parsing and transformation.

def tokenize_smt2_sexpr(expr: str) -> List[str]:
    """Tokenize an SMT2 S-expression string into tokens including parentheses."""
    tokens: List[str] = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in '()':
            tokens.append(c)
            i += 1
            continue
        if c == '|':
            start = i
            i += 1
            while i < n:
                if expr[i] == '|' and (i == start + 1 or expr[i - 1] != '\\'):
                    tokens.append(expr[start:i + 1])
                    i += 1
                    break
                elif expr[i] == '\\' and i + 1 < n and expr[i + 1] == '|':
                    i += 2
                else:
                    i += 1
            else:
                raise ValueError(
                    f"Unterminated quoted SMT symbol at character {start}"
                )
            continue
        if c == '"':
            start = i
            i += 1
            while i < n:
                if expr[i] == '"' and expr[i - 1] != '\\':
                    tokens.append(expr[start:i + 1])
                    i += 1
                    break
                i += 1
            else:
                raise ValueError(
                    f"Unterminated SMT string at character {start}"
                )
            continue
        start = i
        while i < n and (not expr[i].isspace()) and expr[i] not in '()':
            i += 1
        tokens.append(expr[start:i])
    return tokens


def parse_smt2_sexpr(tokens: List[str]) -> Optional[object]:
    """Parse exactly one complete SMT2 S-expression, or return ``None``."""
    stack: List[List[object]] = [[]]
    for t in tokens:
        if t == '(':
            new_list: List[object] = []
            stack[-1].append(new_list)
            stack.append(new_list)
        elif t == ')':
            if len(stack) == 1:
                return None
            stack.pop()
        else:
            stack[-1].append(t)
    if len(stack) != 1 or len(stack[0]) != 1:
        return None
    return stack[0][0]


def serialize_smt2_sexpr(node: object) -> str:
    """Serialize an S-expression AST without depending on Python recursion."""
    chunks: List[str] = []
    pending: List[Tuple[str, object]] = [("node", node)]

    while pending:
        kind, value = pending.pop()
        if kind == "text":
            chunks.append(str(value))
            continue
        if isinstance(value, str):
            chunks.append(value)
            continue
        if not isinstance(value, list):
            chunks.append(str(value))
            continue
        if not value:
            chunks.append("()")
            continue

        chunks.append("(")
        pending.append(("text", ")"))
        for child_index in range(len(value) - 1, -1, -1):
            pending.append(("node", value[child_index]))
            if child_index > 0:
                pending.append(("text", " "))

    return "".join(chunks)


def deep_copy_ast(node: object) -> object:
    """Deep copy an AST without depending on Python recursion."""
    results: List[object] = []
    pending: List[Tuple[str, object]] = [("visit", node)]

    while pending:
        kind, value = pending.pop()
        if kind == "build":
            child_count = int(value)
            children = results[-child_count:] if child_count else []
            if child_count:
                del results[-child_count:]
            results.append(children)
            continue
        if not isinstance(value, list):
            results.append(value)
            continue

        pending.append(("build", len(value)))
        for child in reversed(value):
            pending.append(("visit", child))

    if len(results) != 1:
        raise ValueError("Invalid SMT AST while copying expression")
    return results[0]


def expand_let_ast(node: object, env: Dict[str, object]) -> object:
    """Expand all lets iteratively using simultaneous SMT-LIB semantics."""
    results: List[object] = []
    pending: List[Tuple[str, object, object]] = [("visit", node, env)]

    while pending:
        kind, value, context = pending.pop()
        if kind == "build":
            child_count = int(value)
            children = results[-child_count:] if child_count else []
            if child_count:
                del results[-child_count:]
            results.append(children)
            continue
        if kind == "bind":
            variables, body_node, outer_env = context
            child_count = len(variables)
            binding_values = results[-child_count:] if child_count else []
            if child_count:
                del results[-child_count:]
            body_env = dict(outer_env)
            body_env.update(zip(variables, binding_values))
            pending.append(("visit", body_node, body_env))
            continue

        current_env = context
        if isinstance(value, str):
            results.append(deep_copy_ast(current_env.get(value, value)))
            continue
        if not isinstance(value, list) or not value:
            results.append(value)
            continue
        if value[0] != "let":
            pending.append(("build", len(value), None))
            for child in reversed(value):
                pending.append(("visit", child, current_env))
            continue
        if len(value) != 3:
            raise ValueError(
                "Malformed let: expected bindings and exactly one body"
            )

        bindings_node, body_node = value[1], value[2]
        if not isinstance(bindings_node, list):
            raise ValueError("Malformed let: bindings must be a list")

        variables = []
        binding_values = []
        for binding in bindings_node:
            if (
                not isinstance(binding, list)
                or len(binding) != 2
                or not isinstance(binding[0], str)
            ):
                raise ValueError(
                    "Malformed let binding: expected (symbol term)"
                )
            variable, binding_value = binding
            if variable in variables:
                raise ValueError(f"Duplicate let binding: {variable}")
            variables.append(variable)
            binding_values.append(binding_value)

        pending.append(
            ("bind", len(binding_values), (variables, body_node, current_env))
        )
        # Binding RHS terms see only the outer environment.
        for binding_value in reversed(binding_values):
            pending.append(("visit", binding_value, current_env))

    if len(results) != 1:
        raise ValueError("Invalid SMT AST while expanding let expressions")
    return results[0]


def expand_let_expressions_ast(expr: str) -> str:
    """Expand all let expressions in a single SMT expression using AST."""
    if not expr or not expr.strip():
        return expr
    tokens = tokenize_smt2_sexpr(expr)
    tree = parse_smt2_sexpr(tokens)
    if tree is None:
        raise ValueError("Expected exactly one complete SMT expression")
    return serialize_smt2_sexpr(expand_let_ast(tree, {}))


def expand_let_expressions_ast_batch(exprs: List[str]) -> List[str]:
    """Expand let expressions in a list of SMT expressions."""
    expanded = []
    for expression_index, expression in enumerate(exprs, 1):
        try:
            expanded.append(expand_let_expressions_ast(expression))
        except Exception as exc:
            raise ValueError(
                f"Failed to expand let in expression {expression_index}: {exc}"
            ) from exc
    return expanded


# SSA_RETURN definitions are inlined before router-local dependency slicing.
_RE_SSA_RETURN = re.compile(r'^SSA_RETURN\d+$')


def _is_ssa_return_definition_ast(tree: object) -> Optional[Tuple[str, object]]:
    """If tree is (assert (= SSA_RETURNn body)), return (name, body_ast); else None."""
    if not isinstance(tree, list) or len(tree) < 2:
        return None
    if tree[0] != 'assert':
        return None
    eq = tree[1]
    if not isinstance(eq, list) or len(eq) != 3 or eq[0] != '=':
        return None
    var = eq[1]
    if not isinstance(var, str) or not _RE_SSA_RETURN.match(var):
        return None
    return (var, eq[2])


def _extract_ssa_return_definitions(
    assert_exprs: List[str],
) -> Tuple[Dict[str, object], Set[int]]:
    """Return SSA_RETURN definitions and their assertion indexes."""
    ssa_defs: Dict[str, object] = {}
    defining_indices: Set[int] = set()
    for i, expr in enumerate(assert_exprs):
        if not expr or not expr.strip():
            continue
        try:
            tokens = tokenize_smt2_sexpr(expr)
            tree = parse_smt2_sexpr(tokens)
            res = _is_ssa_return_definition_ast(tree)
            if res is not None:
                name, body_ast = res
                ssa_defs[name] = body_ast
                defining_indices.add(i)
        except Exception:
            continue
    return (ssa_defs, defining_indices)


def _substitute_ssa_return_ast(
    node: object,
    definitions: Dict[str, object],
    substituting: Set[str],
) -> object:
    """Replace every SSA_RETURNn in AST with its body (recursive; avoiding cycles)."""
    if isinstance(node, str):
        if node in definitions and node not in substituting:
            body = definitions[node]
            return _substitute_ssa_return_ast(
                deep_copy_ast(body),
                definitions,
                substituting | {node},
            )
        return node
    if not isinstance(node, list):
        return node
    return [
        _substitute_ssa_return_ast(child, definitions, substituting)
        for child in node
    ]


def expand_ssa_return_in_asserts(
    assert_exprs: List[str],
) -> Tuple[List[str], Set[str]]:
    """Inline SSA_RETURN definitions and remove their defining assertions."""
    ssa_defs, defining_indices = _extract_ssa_return_definitions(assert_exprs)
    if not ssa_defs:
        return (list(assert_exprs), set())

    new_asserts: List[str] = []
    for i, expr in enumerate(assert_exprs):
        if i in defining_indices:
            continue
        if not expr or not expr.strip():
            new_asserts.append(expr)
            continue
        try:
            tokens = tokenize_smt2_sexpr(expr)
            tree = parse_smt2_sexpr(tokens)
            if tree is None:
                new_asserts.append(expr)
                continue
            new_tree = _substitute_ssa_return_ast(tree, ssa_defs, set())
            new_asserts.append(serialize_smt2_sexpr(new_tree))
        except Exception:
            new_asserts.append(expr)
    return (new_asserts, set(ssa_defs.keys()))


def is_symbolic_atom(tok: str) -> bool:
    """True if token is a symbolic variable (not keyword or constant)."""
    if tok in _SMT2_KEYWORDS:
        return False
    if (
        _RE_BIN_CONST.fullmatch(tok)
        or _RE_HEX_CONST.fullmatch(tok)
        or _RE_DEC_CONST.fullmatch(tok)
    ):
        return False
    return True


def _free_symbolic_variables(
    node: object,
    environment: Dict[str, Set[str]],
) -> Set[str]:
    if isinstance(node, str):
        if node in environment:
            return environment[node]
        return {node} if is_symbolic_atom(node) else set()
    if not isinstance(node, list) or not node:
        return set()

    if node[0] == "let" and len(node) >= 3:
        bindings_node, body_node = node[1], node[2]
        if not isinstance(bindings_node, list):
            return _free_symbolic_variables(body_node, environment)
        bindings: Dict[str, Set[str]] = {}
        for binding in bindings_node:
            if (
                isinstance(binding, list)
                and len(binding) >= 2
                and isinstance(binding[0], str)
            ):
                bindings[binding[0]] = _free_symbolic_variables(
                    binding[1], environment
                )
        extended_environment = dict(environment)
        extended_environment.update(bindings)
        return _free_symbolic_variables(body_node, extended_environment)

    variables: Set[str] = set()
    for child in node:
        variables.update(_free_symbolic_variables(child, environment))
    return variables


def extract_symbolic_variables_let_aware(expr: str) -> List[str]:
    """Extract symbolic variables while respecting local let bindings."""
    tokens = tokenize_smt2_sexpr(expr)
    tree = parse_smt2_sexpr(tokens)
    if tree is None:
        return []
    return sorted(_free_symbolic_variables(tree, {}))


# Parentheses and destination-prefix constraints.

def find_matching_paren(text: str, start: int) -> int:
    """Find matching closing paren for opening paren at start. Skips string literals."""
    if start >= len(text) or text[start] != '(':
        return -1
    depth = 1
    i = start + 1
    while i < len(text) and depth > 0:
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
        elif text[i] == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == '\\' and i + 1 < len(text) else 1
            continue
        i += 1
    return i - 1 if depth == 0 else -1


def prefix_string_to_constraint_tuple(
    ip_mask: str,
    variable: str = "|0_dst-ip|",
) -> Optional[Tuple[int, int, str, str]]:
    """Return the SMT extract tuple for one destination prefix."""
    try:
        network = ipaddress.ip_network(ip_mask, strict=False)
        prefix_length = network.prefixlen
        ip_int = int(network.network_address)
        high_bit = 31
        low_bit = 32 - prefix_length
        if prefix_length % 4 == 0:
            extracted_value = (ip_int >> (32 - prefix_length)) & (
                (1 << prefix_length) - 1
            )
            value_str = f"#x{extracted_value:x}"
        else:
            extracted_value = (ip_int >> (32 - prefix_length)) & (
                (1 << prefix_length) - 1
            )
            value_str = f"#b{format(extracted_value, f'0{prefix_length}b')}"
        return (high_bit, low_bit, variable, value_str)
    except (ValueError, AttributeError, ImportError):
        return None


def prefix_string_to_constraint(
    ip_mask: str,
    variable: str = "|0_dst-ip|",
) -> Optional[str]:
    """Convert IP prefix string (e.g. 192.0.2.0/24) to SMT constraint string."""
    result = prefix_string_to_constraint_tuple(ip_mask, variable)
    if not result:
        return None
    high_bit, low_bit, var, value_str = result
    return f"(= ((_ extract {high_bit} {low_bit}) {var}) {value_str})"


# Z3 output and model parsing.

def parse_z3_output(result) -> Tuple[bool, str]:
    """Parse Z3 output and return (is_sat, output_message).

    Handles SAT/UNSAT on the first non-empty line (supports trailing get-model output),
    errors, and compatibility for "unknown constant" errors.
    """
    output = result.stdout.strip()
    if result.stderr.strip():
        logger.warning(f"Z3 stderr: {result.stderr.strip()}")

    first_result_line = ""
    for line in output.splitlines():
        candidate = line.strip().lower()
        if candidate:
            first_result_line = candidate
            break

    # First line is authoritative even when get-model adds a model (sat) or reports
    # "(error \"model is not available\")" after unsat.
    if first_result_line == "sat":
        return True, "sat"
    if first_result_line == "unsat":
        return False, "unsat"

    if result.returncode != 0:
        logger.warning(f"Z3 return code: {result.returncode}")

    if "(error" in output:
        lines = output.split('\n')
        error_lines = [line for line in lines if line.startswith('(error')]
        if error_lines:
            error_msg = '; '.join(error_lines)
            if "unknown constant" in error_msg:
                logger.warning(f"Compatibility issue detected: {error_msg}")
                logger.info(
                    "Attempting to extract SAT/UNSAT result despite the error..."
                )
                last_line = ""
                for line in reversed(lines):
                    line = line.strip()
                    if line and not line.startswith('(error'):
                        last_line = line
                        break
                if last_line == "sat":
                    logger.info("✓ Extracted result: SAT (compatibility mode)")
                    return True, "sat (compatibility mode)"
                if last_line == "unsat":
                    logger.info("✓ Extracted result: UNSAT (compatibility mode)")
                    return False, "unsat (compatibility mode)"
                logger.warning(f"Could not extract SAT/UNSAT. Last line: '{last_line}'")
                return False, f"Z3 error: {error_msg}"
            return False, f"Z3 error: {error_msg}"

    if output == "sat":
        return True, output
    if output == "unsat":
        return False, output
    logger.warning(f"Unexpected Z3 output: {output}")
    return False, f"Unexpected output: {output}"


def append_check_sat(content: str) -> str:
    """Append (check-sat) to SMT2 content if not already present."""
    content = content.rstrip()
    if util_keyword.SMT_CHECK_SAT not in content:
        content += f"\n{util_keyword.SMT_CHECK_SAT}"
    return content + "\n"


def append_get_model(content: str) -> str:
    """Append (get-model) after (check-sat) if not already present."""
    content = content.rstrip()
    if util_keyword.SMT_GET_MODEL in content:
        return content + "\n"
    if util_keyword.SMT_CHECK_SAT in content:
        replacement = (
            f"{util_keyword.SMT_CHECK_SAT}\n{util_keyword.SMT_GET_MODEL}"
        )
        content = content.replace(util_keyword.SMT_CHECK_SAT, replacement, 1)
    else:
        content += f"\n{util_keyword.SMT_GET_MODEL}"
    return content + "\n"


_Z3_QUOTED_MODEL_SYMBOL_RE = re.compile(
    r"\(define-fun\s+(\|[^|]+\|)\s+\(\)"
)
_INTERNET2_EXPORT_ENV_DECL_RE = re.compile(
    r"declare-fun (\|0_[^|]+_BGP_EXPORT_ENV-[^|]+_permitted\|)"
)
_INTERNET2_EXPORT_ENV_FALSE_ASSERT_RE = re.compile(
    r"^\(assert \(= (\|0_[^|]+_BGP_EXPORT_ENV-[^|]+_permitted\|) false\)\)$"
)
_INTERNET2_CONSTRAINT_VAR_RE = re.compile(r"(\|[^|]+\||Config_[^\s()]+)")


def _parse_z3_assignment_at_line(
    lines: List[str],
    index: int,
    symbol_pattern: re.Pattern,
) -> Tuple[Optional[str], Optional[str], int]:
    """Parse one scalar or multiline ``define-fun`` assignment."""
    stripped = lines[index].strip()
    variable_match = symbol_pattern.search(stripped)
    if not variable_match:
        return None, None, index

    variable_name = variable_match.group(1)
    type_match = re.search(r"\(\)\s+((?:\([^\)]+\)|[^\s\(]+))", stripped)
    if not type_match:
        return None, None, index

    remaining = stripped[type_match.end() :].strip()
    if remaining and not remaining.startswith("("):
        value = remaining.rstrip(")").strip()
        return variable_name, re.sub(r"\s+", " ", value), index

    value_parts: List[str] = []
    last_index = index
    parenthesis_depth = stripped.count("(") - stripped.count(")")
    while last_index + 1 < len(lines) and parenthesis_depth > 0:
        last_index += 1
        next_line = lines[last_index].strip()
        parenthesis_depth += next_line.count("(") - next_line.count(")")
        if parenthesis_depth == 0:
            if next_line.endswith(")"):
                value_parts.append(next_line[:-1].strip())
            break
        value_parts.append(next_line)

    value = " ".join(value_parts).strip()
    if not value:
        return None, None, last_index
    return variable_name, re.sub(r"\s+", " ", value), last_index


def parse_z3_model_assignments(model_output: str) -> Dict[str, str]:
    """Parse quoted-symbol assignments from a Z3 ``get-model`` response."""
    assignments: Dict[str, str] = {}
    lines = model_output.splitlines()
    index = 0
    while index < len(lines):
        variable, value, last_index = _parse_z3_assignment_at_line(
            lines,
            index,
            _Z3_QUOTED_MODEL_SYMBOL_RE,
        )
        if variable and value:
            assignments[variable] = value
            index = last_index + 1
        else:
            index += 1
    return assignments


def patch_internet2_export_env_assumptions(
    content: str,
    device: str,
) -> Tuple[str, int]:
    """Set every declared Internet2 BGP EXPORT_ENV permitted flag to false."""
    permitted_variables = sorted(
        set(_INTERNET2_EXPORT_ENV_DECL_RE.findall(content)),
        key=str.lower,
    )
    if not permitted_variables:
        return content, 0

    cleaned_lines: List[str] = []
    lines = content.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith(_INTERNET2_EXPORT_ENV_ASSUME_MARKER):
            index += 1
            while index < len(lines):
                next_stripped = lines[index].strip()
                if not next_stripped:
                    index += 1
                    continue
                if _INTERNET2_EXPORT_ENV_FALSE_ASSERT_RE.match(next_stripped):
                    index += 1
                    continue
                break
            if index < len(lines) and not lines[index].strip():
                index += 1
            continue
        if _INTERNET2_EXPORT_ENV_FALSE_ASSERT_RE.match(stripped):
            index += 1
            continue
        cleaned_lines.append(lines[index])
        index += 1

    while (
        len(cleaned_lines) > 1
        and not cleaned_lines[-1].strip()
        and not cleaned_lines[-2].strip()
    ):
        cleaned_lines.pop()

    check_sat_index = next(
        (
            line_index
            for line_index, line in enumerate(cleaned_lines)
            if line.strip() == util_keyword.SMT_CHECK_SAT
        ),
        None,
    )
    if check_sat_index is None:
        raise ValueError(f"missing {util_keyword.SMT_CHECK_SAT}")

    prefix = cleaned_lines[:check_sat_index]
    while prefix and not prefix[-1].strip():
        prefix.pop()
    suffix = cleaned_lines[check_sat_index:]
    while len(suffix) > 1 and not suffix[-1].strip():
        suffix.pop()

    assert_block = [
        f"{_INTERNET2_EXPORT_ENV_ASSUME_MARKER} {device}",
        *(
            f"(assert (= {variable} false))"
            for variable in permitted_variables
        ),
    ]
    block_lines = [f"{line}\n" for line in assert_block]
    updated = "".join(prefix + ["\n"] + block_lines + ["\n"] + suffix)
    return updated, len(permitted_variables)


def extract_internet2_constraint_variables(content: str) -> Set[str]:
    """Extract variables referenced by Internet2 dataplane constraints."""
    return set(_INTERNET2_CONSTRAINT_VAR_RE.findall(content))


def update_equality_values(
    content: str,
    model: Dict[str, str],
) -> Tuple[str, int]:
    """Replace model-backed equality values, including nested equalities."""
    changes = 0
    updated = content
    for variable, new_value in model.items():
        pattern = re.compile(
            rf"(?P<prefix>\(=\s+{re.escape(variable)}\s+)"
            rf"(?P<value>[^\s()]+)(?=\s*\))"
        )

        def replace(match: re.Match) -> str:
            nonlocal changes
            changes += match.group("value") != new_value
            return f"{match.group('prefix')}{new_value}"

        updated = pattern.sub(replace, updated)
    return updated, changes


def _extract_assertion_content(constraint: str) -> str:
    constraint = constraint.strip()
    if constraint.startswith("(assert "):
        content = constraint[8:]
        if content.endswith(")"):
            content = content[:-1]
        return content.strip()
    return constraint


def _combine_assertion_constraints(
    constraints: Sequence[str],
    operator: str,
    empty_value: str,
) -> str:
    contents = [
        content
        for content in (
            _extract_assertion_content(constraint)
            for constraint in constraints
        )
        if content
    ]
    return _combine_smt_expressions(contents, operator, empty_value)


def build_combined_negated_constraint(
    normal_stable_constraints: List[str],
    negated_stable_constraints: List[str],
    negated_route_constraints: List[str],
) -> str:
    """Build the router-level combined negated constraint expression."""
    negated_stable = _combine_assertion_constraints(
        negated_stable_constraints, "or", "false"
    )
    normal_stable = _combine_assertion_constraints(
        normal_stable_constraints, "and", "true"
    )
    negated_route = _combine_assertion_constraints(
        negated_route_constraints, "and", "true"
    )

    if normal_stable == "true" and negated_route == "true":
        combined_and = "true"
    elif normal_stable == "true":
        combined_and = negated_route
    elif negated_route == "true":
        combined_and = normal_stable
    else:
        combined_and = f"(and {normal_stable} {negated_route})"

    if negated_stable == "false" and combined_and == "true":
        return "true"
    if negated_stable == "false":
        return combined_and
    if combined_and == "true":
        return "true"
    return f"(or {negated_stable} {combined_and})"


def run_z3_get_model(
    smt_content: str,
) -> Tuple[bool, str, Dict[str, str]]:
    """Run Z3 with ``get-model`` and return satisfiability and assignments."""
    result = run_z3_text(append_get_model(smt_content.rstrip() + "\n"))
    output = result.stdout.strip()
    is_sat, status = parse_z3_output(result)
    assignments = parse_z3_model_assignments(output) if is_sat else {}
    diagnostic = status if is_sat else output.splitlines()[0] if output else status
    return is_sat, diagnostic, assignments


def build_smt_simplify_command(
    tactics: Sequence[str] = util_keyword.SMT_SIMPLIFICATION_TACTICS,
) -> str:
    """Build one Z3 ``apply`` command from an ordered tactic sequence."""
    return f"(apply (then {' '.join(tactics)}))"


def replace_check_sat_with_simplify(
    content: str,
    tactics: Sequence[str] = util_keyword.SMT_SIMPLIFICATION_TACTICS,
) -> str:
    """Replace ``check-sat`` with a Z3 simplification goal command."""
    command = build_smt_simplify_command(tactics)
    replacement = f"; {util_keyword.SMT_CHECK_SAT}\n{command}"
    if util_keyword.SMT_CHECK_SAT in content:
        return content.replace(util_keyword.SMT_CHECK_SAT, replacement)
    return f"{content.rstrip()}\n{replacement}\n"


_CONSISTENCY_ENCODING_ROUTER_RE = re.compile(
    rf"(?:{re.escape(util_keyword.SATISFACTION_CHECK_FILE_PREFIX)}|"
    rf"{re.escape(util_keyword.VIOLATION_CHECK_FILE_PREFIX)})"
    r"_([^.]+)\.smt2$"
)


def get_consistency_router_from_smt2_path(
    file_path: Union[str, Path],
) -> Optional[str]:
    """Return the router name from a stage-3 consistency-check filename."""
    match = _CONSISTENCY_ENCODING_ROUTER_RE.search(Path(file_path).name)
    return match.group(1) if match else None


def get_device_for_config_var(config_var, devices: List[str]) -> Optional[str]:
    """Get device for processing a Config variable occurrence.

    Prefer the consistency-check host because a Config variable may name a
    different router. Fall back to the Config prefix for non-check files.
    """
    host = get_consistency_router_from_smt2_path(config_var.file_path)
    if host:
        return host
    for device in sorted(devices, key=len, reverse=True):
        if config_var.name.startswith(f'Config_{device}_'):
            return device
    name_match = re.search(
        r'^Config_([a-zA-Z0-9_-]+?)_'
        r'(RouteFilterList|RoutingPolicy|CommunityList)',
        config_var.name,
    )
    if name_match:
        potential_device = name_match.group(1)
        if potential_device in devices:
            return potential_device
    return None


# Subspec extraction and conversion.

def strip_subspec_suffixes(subspec: str) -> Tuple[str, str]:
    """Separate presentation suffixes from the core subspec."""
    if not subspec or subspec.strip() == "empty":
        return (subspec, "")
    rest = subspec.strip()
    suffix_parts: List[str] = []
    m_from = re.search(r"\s+\[from\s+(\S+)\]$", rest)
    if m_from:
        suffix_parts.append(f" [from {m_from.group(1)}]")
        rest = rest[: m_from.start()].strip()
    and_clause_re = re.compile(
        r"\s+AND\s+(configurable|nonconfigurable)"
        r"(\s+\(permit\)|\s+\(deny\))?\s*=\s*\{[^}]*\}\s*$"
    )
    while True:
        m = and_clause_re.search(rest)
        if not m:
            break
        suffix_parts.append(rest[m.start() :])
        rest = rest[: m.start()].strip()
    suffix_to_restore = "".join(reversed(suffix_parts))
    return (rest, suffix_to_restore)


def extract_community_lists_from_line_subspec(
    subspec: str,
) -> Optional[Tuple[List[str], List[str], List[str], List[str]]]:
    """Extract the four community groups from a line-level subspec."""
    if not subspec or subspec.strip() == "empty":
        return None

    groups = []
    for key in (
        "configurable (permit)",
        "nonconfigurable (permit)",
        "configurable (deny)",
        "nonconfigurable (deny)",
    ):
        pattern = re.compile(
            rf"\b{re.escape(key)}\s*=\s*\{{([^}}]*)\}}",
            re.IGNORECASE,
        )
        match = pattern.search(subspec)
        if match is None:
            return None
        groups.append(
            [
                item.strip()
                for item in match.group(1).split(",")
                if item.strip()
            ]
        )
    return groups[0], groups[1], groups[2], groups[3]


def get_action_from_core_subspec(core_subspec: str) -> Optional[bool]:
    """Determine action (permit/deny) from core line-level subspec."""
    if not core_subspec:
        return None
    # Allow hyphen in config name for hostnames like edge-15, aggregation-12
    if re.search(r"\(\s*=\s+Config_[a-zA-Z0-9_-]+_action\s+true\s*\)", core_subspec):
        return True
    if re.search(r"\(\s*=\s+Config_[a-zA-Z0-9_-]+_action\s+false\s*\)", core_subspec):
        return False
    return None


def extract_smt_variables_from_line(line: str) -> Set[str]:
    """Return quoted symbols and bare Config/SSA variables in one expression."""
    variables = set()
    variables.update(re.findall(r'\|[^|]+\|', line))
    variables.update(
        re.findall(
            r'(?<![a-zA-Z0-9_-])Config_[a-zA-Z0-9_-]+',
            line,
        )
    )
    variables.update(
        re.findall(
            r'(?<![a-zA-Z0-9_-])SSA_[a-zA-Z0-9_-]+',
            line,
        )
    )
    return variables


def unwrap_smt_goal_content(content: str) -> List[str]:
    """Return assertion expressions from one Z3 ``goal`` expression."""
    content = content.strip()
    if not content.startswith("(goal ") and not content.startswith("(goal\n"):
        return [content]
    try:
        tokens = tokenize_smt2_sexpr(content)
        tree = parse_smt2_sexpr(tokens)
        if tree is None or not isinstance(tree, list) or not tree or tree[0] != "goal":
            return [content]
        assertions = []
        i = 1
        while i < len(tree):
            child = tree[i]
            if isinstance(child, str) and child.startswith(":"):
                i += 2
                continue
            if isinstance(child, list) and child:
                assertions.append(serialize_smt2_sexpr(child))
            i += 1
        return assertions if assertions else [content]
    except Exception:
        return [content]


def parse_smt_goals(output: str) -> List[dict]:
    """Parse the assertion entries contained in Z3 ``(goals ...)`` output."""
    lines = output.split('\n')
    goals_data = []
    current_line = ""
    paren_count = 0
    in_goal = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("(goals") or line.startswith("(goal"):
            in_goal = True
            continue
        if not in_goal:
            continue
        for char in line:
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
        current_line += " " + line
        if paren_count == 0 and current_line.strip():
            content = current_line.strip()
            if content and content != ")":
                goals_data.append(
                    {
                        'content': content,
                        'line_number': len(goals_data) + 1,
                    }
                )
            current_line = ""
    return goals_data


def replace_config_variables_in_subspec(
    subspec: str,
    line1_variable_names: Optional[Set[str]] = None,
    lineN_variable_names: Optional[Set[str]] = None,
    config_mapping: Optional[Dict[str, str]] = None
) -> str:
    """Replace Line1 Config variables with their target-line counterparts."""
    if not subspec:
        return subspec
    if config_mapping:
        mapping = config_mapping
    elif line1_variable_names and lineN_variable_names:
        mapping: Dict[str, str] = {}
        for line1_var in line1_variable_names:
            last_underscore = line1_var.rfind('_')
            if last_underscore == -1:
                continue
            field_name = line1_var[last_underscore + 1:]
            for lineN_var in lineN_variable_names:
                if lineN_var.endswith(f'_{field_name}'):
                    mapping[line1_var] = lineN_var
                    break
        if not mapping:
            return subspec
    else:
        return subspec
    result = subspec
    for old_var, new_var in sorted(
        mapping.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        pattern = rf'(?<![a-zA-Z0-9_-]){re.escape(old_var)}(?![a-zA-Z0-9_-])'
        result = re.sub(pattern, new_var, result)
    vars_to_check = list(mapping.keys())
    target_vars_to_check = list(mapping.values())
    if vars_to_check and target_vars_to_check:
        line1_pattern = None
        for line1_var in vars_to_check:
            prefix_match = re.search(r'(Config_[^_]+(?:__[^_]+)*__Line1__)', line1_var)
            if prefix_match:
                line1_pattern = prefix_match.group(1)
                break
        if line1_pattern:
            lineN_pattern = None
            for lineN_var in target_vars_to_check:
                prefix_match = re.search(
                    r'(Config_[^_]+(?:__[^_]+)*__Line\d+__)',
                    lineN_var,
                )
                if prefix_match:
                    lineN_pattern = prefix_match.group(1)
                    break
            if lineN_pattern:
                remaining_pattern = (
                    rf'(?<![a-zA-Z0-9_-]){re.escape(line1_pattern)}'
                    rf'[^)\s]+(?![a-zA-Z0-9_-])'
                )
                if re.search(remaining_pattern, result):
                    def replace_remaining(match):
                        return match.group(0).replace(line1_pattern, lineN_pattern, 1)
                    result = re.sub(remaining_pattern, replace_remaining, result)
    return result


def extract_config_constraints_from_z3_goal(
    z3_output: str,
    config_names: Set[str],
    original_constraints_map: Optional[Dict[str, str]] = None
) -> str:
    """Extract Config variable constraints from Z3 simplification goal output."""
    if not z3_output or not config_names:
        return ""
    constraint_parts = extract_smt_goal_dependency_closure(
        z3_output, config_names
    )
    if not constraint_parts:
        return ""
    if original_constraints_map:
        found_config_names = set()
        for constraint in constraint_parts:
            found_config_names.update(re.findall(r'Config_[a-zA-Z0-9_-]+', constraint))
            found_config_names.update(
                match.strip("|")
                for match in re.findall(
                    r'\|Config_[a-zA-Z0-9_-]+\|', constraint
                )
            )
        missing_config_names = config_names - found_config_names
        if missing_config_names:
            for missing_config_name in sorted(missing_config_names):
                if missing_config_name in original_constraints_map:
                    orig = original_constraints_map[missing_config_name]
                    if " AND " in orig:
                        constraint_parts.extend(
                            part.strip()
                            for part in orig.split(" AND ")
                            if part.strip()
                        )
                    else:
                        constraint_parts.append(orig)
    if constraint_parts:
        return " AND ".join(constraint_parts)
    return ""


def _iter_goal_assertion_contents(z3_output: str) -> List[str]:
    """Flat list of goal assertion strings from Z3 simplify output."""
    goals_data = parse_smt_goals(z3_output)
    assertions: List[str] = []
    for line_data in goals_data:
        content = line_data["content"].strip()
        if not content or content.startswith(":") or content in ("(goal", ")"):
            continue
        if content.startswith("(goal ") or content.startswith("(goal\n"):
            for assertion in unwrap_smt_goal_content(content):
                if assertion and assertion != ")":
                    assertions.append(assertion)
        else:
            assertions.append(content)
    return assertions


def extract_smt_goal_dependency_closure(
    z3_output: str,
    target_variables: Set[str],
) -> List[str]:
    """Return the complete assertion dependency closure of target variables."""
    assertions = _iter_goal_assertion_contents(z3_output)
    if not assertions or not target_variables:
        return []

    variables_by_assertion = []
    assertions_by_variable: Dict[str, List[int]] = {}
    for assertion_index, assertion in enumerate(assertions):
        variables = extract_smt_variables_from_line(assertion)
        variables_by_assertion.append(variables)
        for variable in variables:
            assertions_by_variable.setdefault(variable, []).append(assertion_index)

    pending_variables = deque()
    visited_variables = set()
    for variable in sorted(target_variables):
        aliases = {variable}
        if variable.startswith("|") and variable.endswith("|"):
            aliases.add(variable[1:-1])
        else:
            aliases.add(f"|{variable}|")
        for alias in sorted(aliases):
            if alias not in visited_variables:
                visited_variables.add(alias)
                pending_variables.append(alias)

    # Ground assertions are global constraints. In particular, dropping ``false``
    # would turn an unsatisfiable goal into a satisfiable projection.
    selected_assertions = {
        assertion_index
        for assertion_index, variables in enumerate(variables_by_assertion)
        if not variables
    }
    while pending_variables:
        variable = pending_variables.popleft()
        for assertion_index in assertions_by_variable.get(variable, []):
            if assertion_index in selected_assertions:
                continue
            selected_assertions.add(assertion_index)
            for related_variable in variables_by_assertion[assertion_index]:
                if related_variable not in visited_variables:
                    visited_variables.add(related_variable)
                    pending_variables.append(related_variable)

    return [
        assertion
        for assertion_index, assertion in enumerate(assertions)
        if assertion_index in selected_assertions
    ]


def partition_configs_by_z3_goal_connectivity(
    z3_output: str,
    config_names: Sequence[str],
) -> List[List[str]]:
    """Partition Config variables by simplification-goal connectivity.

    Co-occurrence in one assertion creates an edge. Bare and quoted forms of
    the same Config variable are aliases; absent variables remain singletons.
    """
    if not config_names:
        return []

    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    # Alias bare Config_xxx with |Config_xxx|
    for name in config_names:
        union(name, f"|{name}|")

    for assertion in _iter_goal_assertion_contents(z3_output or ""):
        vars_in_line = list(extract_smt_variables_from_line(assertion))
        if len(vars_in_line) < 2:
            if len(vars_in_line) == 1:
                find(vars_in_line[0])
            continue
        head = vars_in_line[0]
        for other in vars_in_line[1:]:
            union(head, other)

    root_to_group: Dict[str, List[str]] = {}
    root_order: List[str] = []
    for name in config_names:
        root = find(name)
        if root not in root_to_group:
            root_to_group[root] = []
            root_order.append(root)
        root_to_group[root].append(name)

    return [root_to_group[r] for r in root_order]


def subspec_string_to_list(subspec: str) -> List[str]:
    """Convert subspec string to list of constraint strings."""
    if not subspec or subspec.strip() in ("", "empty"):
        return []
    return [part.strip() for part in subspec.split(" AND ") if part.strip()]


def subspec_string_to_smt2_and(subspec: str) -> str:
    """Convert subspec string to SMT2 (and ...) format."""
    if not subspec or subspec.strip() in ("", "empty"):
        return ""
    parts = subspec_string_to_list(subspec)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(and " + " ".join(parts) + ")"


def subspec_to_smt2_asserts(subspec: str) -> List[str]:
    """Convert subspec string to list of SMT2 assert statements."""
    if subspec == "empty" or not subspec.strip():
        return []
    return subspec_string_to_list(subspec)


def build_smt_simplification_input(
    subspec: str,
    *,
    config_name: str,
    declares: Sequence[str],
    iteration: int,
) -> str:
    """Build the SMT2 input used by iterative subspec normalization."""
    expressions = subspec_to_smt2_asserts(subspec)
    if not expressions:
        return ""

    lines = [
        "; Z3 Simplification SMT file",
        f"; Generated for {config_name}",
        f"; Iteration: {iteration}",
        "",
        "; Declarations from metadata file",
        *sorted(set(declares)),
        "",
        "; Assert statements from subspec",
        *(f"(assert {expression})" for expression in expressions),
        "",
        "; Apply simplification",
        build_smt_simplify_command(),
    ]
    return "\n".join(lines)


def extract_constraints_excluding_field(
    line_level_subspecs: str,
    field_names: List[str],
) -> List[str]:
    """Return line constraints that do not reference the given fields."""
    if not line_level_subspecs or line_level_subspecs.strip() in ("", "empty"):
        return []
    if not field_names:
        return subspec_string_to_list(line_level_subspecs)
    constraints = subspec_string_to_list(line_level_subspecs)
    return [c for c in constraints if not any(fn in c for fn in field_names)]


def get_bounds_for_single_config_variable(config_var_name: str) -> List[str]:
    """Get bounds constraints for a single config variable based on its suffix."""
    bounds = []
    if config_var_name.endswith(
        ('_length', '_prefix_range_start', '_prefix_range_end')
    ):
        bounds.append(f"(assert (>= {config_var_name} 0))")
        bounds.append(f"(assert (<= {config_var_name} 32))")
        if config_var_name.endswith('_length'):
            base_name = config_var_name[:-7]
            bounds.append(
                f"(assert (>= {base_name}_prefix_range_start "
                f"{config_var_name}))"
            )
            bounds.append(
                f"(assert (>= {base_name}_prefix_range_end "
                f"{config_var_name}))"
            )
        elif config_var_name.endswith('_prefix_range_start'):
            base_name = config_var_name[:-19]
            bounds.append(f"(assert (>= {config_var_name} {base_name}_length))")
        elif config_var_name.endswith('_prefix_range_end'):
            base_name = config_var_name[:-17]
            bounds.append(f"(assert (>= {config_var_name} {base_name}_length))")
    elif config_var_name.endswith('_prepend_aspath_cost'):
        bounds.append(f"(assert (>= {config_var_name} 0))")
    elif (
        '_set_localpreference_' in config_var_name
        or '_set_metric_' in config_var_name
    ):
        bounds.append(f"(assert (>= {config_var_name} 0))")
        bounds.append(f"(assert (<= {config_var_name} 4294967295))")
    return bounds


def get_bounds_for_multiple_config_variables(config_var_names: List[str]) -> List[str]:
    """Get bounds for multiple config variables, deduplicated."""
    seen: Set[str] = set()
    result: List[str] = []
    for name in config_var_names:
        for b in get_bounds_for_single_config_variable(name):
            if b not in seen:
                seen.add(b)
                result.append(b)
    return sorted(result)


def is_ip_mask_pair(var1_name: str, var2_name: str) -> bool:
    """Check if two config variable names form an ip/mask pair."""
    if var1_name.endswith("__ip") and var2_name.endswith("__mask"):
        return var1_name[:-4] == var2_name[:-6]
    if var1_name.endswith("__mask") and var2_name.endswith("__ip"):
        return var1_name[:-6] == var2_name[:-4]
    return False


def extract_base_name_for_ip_mask(var_name: str) -> str:
    """Extract base name from an ip or mask variable."""
    if var_name.endswith("__ip"):
        return var_name[:-4]
    if var_name.endswith("__mask"):
        return var_name[:-6]
    return var_name


def get_mask_variable_names_from_pairs(pairs: List[Tuple[str, str]]) -> Set[str]:
    """Return mask variable names from ``(ip, mask)`` pairs."""
    return {mask_name for (_ip_name, mask_name) in pairs}
