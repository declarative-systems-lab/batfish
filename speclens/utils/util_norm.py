#!/usr/bin/env python3
"""Subspec normalization rules and iterative normalization orchestration."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional, Set, Tuple

from utils import util_file, util_keyword
from utils.util_log import get_logger
from utils.util_smt import (
    build_smt_simplification_input,
    expand_let_expressions_ast,
    extract_smt_goal_dependency_closure,
    find_matching_paren,
    negate_smt_expression,
    prefix_string_to_constraint_tuple,
    require_successful_z3_output,
    run_z3_text,
    parse_smt2_sexpr,
    serialize_smt2_sexpr,
    tokenize_smt2_sexpr,
)

logger = get_logger(__name__)

_SUBSPEC_SEPARATOR = " AND "
_SMT_VARIABLE_PATTERN = r"(?:Config_[a-zA-Z0-9_-]+|\|[^|]+\|)"
_CONFIG_VARIABLE_PATTERN = r"Config_[a-zA-Z0-9_-]+"
_COMPARISON_CONSTRAINT_RE = re.compile(
    rf"\((>=|<=|>|<)\s+({_SMT_VARIABLE_PATTERN})\s+(-?\d+)\)"
)
_REVERSED_COMPARISON_RES = (
    (re.compile(rf"\(>=\s+(\d+)\s+({_SMT_VARIABLE_PATTERN})\)"), "<="),
    (re.compile(rf"\(<=\s+(\d+)\s+({_SMT_VARIABLE_PATTERN})\)"), ">="),
    (re.compile(rf"\(>\s+(\d+)\s+({_SMT_VARIABLE_PATTERN})\)"), "<"),
    (re.compile(rf"\(<\s+(\d+)\s+({_SMT_VARIABLE_PATTERN})\)"), ">"),
)
_EXTRACT_CONSTRAINT_RE = re.compile(
    r"\(=\s+\(\(_\s+extract\s+(\d+)\s+(\d+)\)\s+([^)]+)\)\s+([^)]+)\)"
)
_COMMUNITY_SUFFIX_RES = (
    re.compile(r"\s+AND\s+configurable", re.IGNORECASE),
    re.compile(r"\s+AND\s+nonconfigurable", re.IGNORECASE),
)
_TRAILING_AND_RE = re.compile(r"\s+AND\s*$")

_ExtractConstraint = Tuple[int, int, str, str]
_LocatedExtractConstraint = Tuple[int, str, _ExtractConstraint]


# Shared subspec representation helpers.


def _split_subspec(subspec: str) -> List[str]:
    """Split the pipeline's custom top-level conjunction representation."""
    if _SUBSPEC_SEPARATOR not in subspec:
        return [subspec.strip()]
    return [
        part.strip()
        for part in subspec.split(_SUBSPEC_SEPARATOR)
        if part.strip()
    ]


def _join_subspec(parts: List[str]) -> str:
    return _SUBSPEC_SEPARATOR.join(parts)


# In-memory normalization rules.


class NormalizationRule(ABC):
    """Base class for deterministic, in-memory normalization rules."""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        """Return the normalized subspec."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', enabled={self.enabled})"


class LetExpressionExpansionRule(NormalizationRule):
    """Expand SMT let expressions using the shared strict AST implementation."""

    def __init__(self, enabled: bool = True):
        super().__init__("Let Expression Expansion", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        parts = _split_subspec(subspec)
        expanded = _join_subspec(
            [expand_let_expressions_ast(part) for part in parts]
        )
        if expanded != subspec:
            logger.info(f"    [{self.name}] Expanded let expressions")
        return expanded


def _rewrite_smt_subspec_ast(subspec: str, rewrite) -> str:
    """Apply one recursive AST rewrite to each custom ``AND``-separated part."""
    rewritten_parts = []
    for part in _split_subspec(subspec):
        tree = parse_smt2_sexpr(tokenize_smt2_sexpr(part))
        if tree is None:
            raise ValueError(f"Malformed SMT expression: {part[:160]}")
        rewritten_parts.append(serialize_smt2_sexpr(rewrite(tree)))
    return _join_subspec(rewritten_parts)


class BitwiseDeMorganRule(NormalizationRule):
    """Apply ``bvnot(bvor(bvnot(A), bvnot(B))) = bvand(A, B)``."""

    def __init__(self, enabled: bool = True):
        super().__init__("Bitwise De Morgan Simplification", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec
        result = _rewrite_smt_subspec_ast(subspec, self._rewrite)
        if result != subspec:
            logger.info(f"    [{self.name}] Simplified bitwise negation")
        return result

    def _rewrite(self, node: object) -> object:
        if not isinstance(node, list):
            return node
        rewritten = [self._rewrite(child) for child in node]
        if len(rewritten) != 2 or rewritten[0] != "bvnot":
            return rewritten
        inner = rewritten[1]
        if not isinstance(inner, list) or len(inner) != 3 or inner[0] != "bvor":
            return rewritten
        left, right = inner[1], inner[2]
        if not self._is_unary(left, "bvnot") or not self._is_unary(right, "bvnot"):
            return rewritten
        return ["bvand", left[1], right[1]]

    @staticmethod
    def _is_unary(node: object, operator: str) -> bool:
        return isinstance(node, list) and len(node) == 2 and node[0] == operator


class LogicalDeMorganRule(NormalizationRule):
    """Apply exact-token Boolean De Morgan and double-negation rewrites."""

    def __init__(self, enabled: bool = True):
        super().__init__("Logical De Morgan Simplification", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec
        result = _rewrite_smt_subspec_ast(subspec, self._rewrite)
        if result != subspec:
            logger.info(f"    [{self.name}] Simplified Boolean negation")
        return result

    def _rewrite(self, node: object) -> object:
        if not isinstance(node, list):
            return node
        rewritten = [self._rewrite(child) for child in node]

        if self._is_unary(rewritten, "not"):
            inner = rewritten[1]
            if self._is_unary(inner, "not"):
                return inner[1]
            if isinstance(inner, list) and len(inner) >= 3 and inner[0] == "or":
                return ["and", *[["not", argument] for argument in inner[1:]]]

        if len(rewritten) >= 3 and rewritten[0] == "or":
            arguments = rewritten[1:]
            if any(self._is_unary(argument, "not") for argument in arguments):
                complements = [
                    argument[1]
                    if self._is_unary(argument, "not")
                    else ["not", argument]
                    for argument in arguments
                ]
                return ["not", ["and", *complements]]
        return rewritten

    @staticmethod
    def _is_unary(node: object, operator: str) -> bool:
        return isinstance(node, list) and len(node) == 2 and node[0] == operator


class ComparisonConstraintReorderingRule(NormalizationRule):
    """Order numeric bounds by variable, direction, and value."""

    def __init__(self, enabled: bool = True):
        super().__init__("Comparison Constraint Reordering", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        if _SUBSPEC_SEPARATOR not in subspec:
            return subspec

        parts = _split_subspec(subspec)
        if len(parts) < 2:
            return subspec

        comparison_parts = []
        other_parts = []

        for part in parts:
            match = _COMPARISON_CONSTRAINT_RE.match(part)
            if match:
                op = match.group(1)
                var = match.group(2)
                value = int(match.group(3))
                comparison_parts.append((op, var, value, part))
            else:
                other_parts.append(part)

        if not comparison_parts:
            return subspec

        def sort_key(item):
            op, var, value, _ = item
            op_priority = {'>=': 0, '>': 1, '<=': 2, '<': 3}.get(op, 4)
            return (var, op_priority, value)

        comparison_parts.sort(key=sort_key)

        result_parts = [item[3] for item in comparison_parts] + other_parts
        result = _join_subspec(result_parts)

        if result != subspec:
            logger.debug(f"    [{self.name}] Reordered comparison constraints")

        return result


class RedundantComparisonEliminationRule(NormalizationRule):
    """Keep the strongest bound for each variable and operator."""

    def __init__(self, enabled: bool = True):
        super().__init__("Redundant Comparison Elimination", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        if _SUBSPEC_SEPARATOR not in subspec:
            return subspec

        parts = _split_subspec(subspec)
        if len(parts) < 2:
            return subspec

        constraints_by_var = {}
        remaining_parts = []
        for part in parts:
            match = _COMPARISON_CONSTRAINT_RE.match(part)
            if match:
                op = match.group(1)
                var = match.group(2)
                value = int(match.group(3))

                constraints_by_var.setdefault(var, {}).setdefault(op, []).append(
                    (value, part)
                )
            else:
                remaining_parts.append(part)

        for var, ops_dict in constraints_by_var.items():
            for op, value_list in ops_dict.items():
                if len(value_list) > 1:
                    if op in ['>=', '>']:
                        value_list.sort(key=lambda x: x[0], reverse=True)
                        remaining_parts.append(value_list[0][1])
                        logger.debug(
                            f"    [{self.name}] Removed redundant {op} "
                            f"constraints for {var}, kept {value_list[0][0]}"
                        )
                    elif op in ['<=', '<']:
                        value_list.sort(key=lambda x: x[0])
                        remaining_parts.append(value_list[0][1])
                        logger.debug(
                            f"    [{self.name}] Removed redundant {op} "
                            f"constraints for {var}, kept {value_list[0][0]}"
                        )
                else:
                    remaining_parts.append(value_list[0][1])

        if len(remaining_parts) == len(parts):
            return subspec

        result = _join_subspec(remaining_parts)

        if result != subspec:
            logger.debug(f"    [{self.name}] Eliminated redundant comparison constraints")

        return result


class ComparisonOperatorNormalizationRule(NormalizationRule):
    """Move numeric constants from the left to the right operand."""

    def __init__(self, enabled: bool = True):
        super().__init__("Comparison Operator Normalization", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        result = subspec
        for pattern, normalized_operator in _REVERSED_COMPARISON_RES:
            result = pattern.sub(
                lambda match, operator=normalized_operator: (
                    f"({operator} {match.group(2)} {match.group(1)})"
                ),
                result,
            )

        if result != subspec:
            logger.debug(f"    [{self.name}] Normalized comparison operators")

        return result


def _extract_next_smt_arg(text: str, start: int) -> Tuple[Optional[str], int]:
    """Extract the next SMT argument starting at start; return (arg, next_index)."""
    i = start
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return None, i
    if text[i] == '(':
        end = find_matching_paren(text, i)
        if end < 0:
            return None, i
        return text[i:end + 1], end + 1
    j = i
    while j < len(text) and not text[j].isspace():
        j += 1
    return text[i:j], j


class IteEqualitySimplificationRule(NormalizationRule):
    """Expand ite equalities when the compared value matches a branch.

    Equivalences:
    - (= (ite C A B) A) -> (or C (= A B))
    - (= (ite C A B) B) -> (or (not C) (= A B))

    Also handles reversed operand order and n-ary equalities. For n-ary equality,
    the equality among all operands other than the simplified ite is preserved.
    """

    def __init__(self, enabled: bool = True, max_iterations: int = 10):
        super().__init__("Ite Equality Simplification", enabled=enabled)
        self.max_iterations = max_iterations

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        if _SUBSPEC_SEPARATOR in subspec:
            parts = _split_subspec(subspec)
            if not parts:
                return subspec
            simplified_parts = [self._simplify_part(part) for part in parts]
            result = _join_subspec(simplified_parts)
        else:
            result = self._simplify_part(subspec)

        if result != subspec:
            logger.info(f"    [{self.name}] Simplified ite equality constraint(s)")
        return result

    def _simplify_part(self, expr: str) -> str:
        result = expr
        changed = True
        iteration = 0

        while changed and iteration < self.max_iterations:
            iteration += 1
            changed = False
            i = 0
            while i < len(result):
                if result[i] == '(':
                    j = i + 1
                    while j < len(result) and result[j].isspace():
                        j += 1
                    if j < len(result) and result[j] == '=':
                        eq_start = i
                        eq_end = find_matching_paren(result, eq_start)
                        if eq_end > 0:
                            eq_expr = result[eq_start:eq_end + 1]
                            simplified = self._try_simplify_ite_equality(eq_expr)
                            if simplified is not None and simplified != eq_expr:
                                result = result[:eq_start] + simplified + result[eq_end + 1:]
                                changed = True
                                i = 0
                                continue
                i += 1

        if iteration >= self.max_iterations:
            logger.warning(f"    [{self.name}] Reached max iterations ({self.max_iterations})")
        return result

    def _try_simplify_ite_equality(self, eq_expr: str) -> Optional[str]:
        operands = self._parse_equality(eq_expr)
        if operands is None:
            return None

        for ite_index, operand in enumerate(operands):
            parsed = self._parse_ite(operand)
            if parsed is None:
                continue
            condition, true_branch, false_branch = parsed
            branches_equal = f"(= {true_branch} {false_branch})"

            for other_index, other in enumerate(operands):
                if other_index == ite_index:
                    continue
                if self._expr_equal(other, true_branch):
                    branch_constraint = f"(or {condition} {branches_equal})"
                elif self._expr_equal(other, false_branch):
                    branch_constraint = (
                        f"(or {negate_smt_expression(condition)} "
                        f"{branches_equal})"
                    )
                else:
                    continue

                remaining = [
                    item
                    for index, item in enumerate(operands)
                    if index != ite_index
                ]
                if len(remaining) == 1:
                    return branch_constraint
                remaining_equality = f"(= {' '.join(remaining)})"
                return f"(and {remaining_equality} {branch_constraint})"
        return None

    def _parse_equality(self, expr: str) -> Optional[List[str]]:
        expr = expr.strip()
        if not expr.startswith('('):
            return None
        end = find_matching_paren(expr, 0)
        if end < 0 or end != len(expr) - 1:
            return None

        inner = expr[1:end]
        i = 0
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i >= len(inner) or inner[i] != '=':
            return None
        i += 1
        if i < len(inner) and not inner[i].isspace():
            return None

        operands = []
        while True:
            operand, i = _extract_next_smt_arg(inner, i)
            if operand is None:
                break
            operands.append(operand)
        return operands if len(operands) >= 2 else None

    def _parse_ite(self, expr: str) -> Optional[Tuple[str, str, str]]:
        expr = expr.strip()
        if not expr.startswith('('):
            return None
        end = find_matching_paren(expr, 0)
        if end < 0 or end != len(expr) - 1:
            return None

        inner = expr[1:end]
        i = 0
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i + 3 > len(inner) or inner[i:i + 3] != 'ite':
            return None
        i += 3
        if i < len(inner) and not inner[i].isspace():
            return None

        c, i = _extract_next_smt_arg(inner, i)
        a, i = _extract_next_smt_arg(inner, i)
        b, i = _extract_next_smt_arg(inner, i)
        if c is None or a is None or b is None:
            return None
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i != len(inner):
            return None
        return c, a, b

    @staticmethod
    def _expr_equal(a: str, b: str) -> bool:
        return a.strip() == b.strip()


class IteBranchConflictSimplificationRule(NormalizationRule):
    """Simplify top-level (ite A B C) when a branch conflicts with sibling constraints.

    Only when B/C is trivially false, internally unsat, or a fully ground-assignable
    conjunction whose assignment falsifies a sibling:
    - If B ∧ Other is proven unsat → replace (ite A B C) with (not A) AND C
    - If C ∧ Other is proven unsat → replace (ite A B C) with A AND B
    - If both → false

    Trivial false includes ``false``, ``(not true)``, and ``(and ... false ...)``.
    A lone ``(ite A false C)`` (no siblings) is also rewritten.

    Does **not** expand ``let`` itself. Callers must ensure lets are already expanded
    (``normalize_subspec`` expands once before the normalizer1 loop; ``normalizer2``
    expands again before this rule for any lets Z3 reintroduced).
    """

    def __init__(self, enabled: bool = True):
        super().__init__("Ite Branch Conflict Simplification", enabled=enabled)

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec
        if subspec == "empty" or not subspec.strip():
            return subspec

        parts = self._split_top_level_conjuncts(subspec)
        if not parts:
            return subspec

        new_parts: List[str] = []
        rewrote_ite = False
        for idx, part in enumerate(parts):
            parsed = self._parse_ite(part)
            if parsed is None:
                new_parts.append(part)
                continue

            a, b, c = parsed
            other_parts = parts[:idx] + parts[idx + 1:]
            b_conflicts = self._branch_conflicts_with_others(b, other_parts)
            c_conflicts = self._branch_conflicts_with_others(c, other_parts)

            if b_conflicts and c_conflicts:
                replacements = ["false"]
            elif b_conflicts:
                # (ite A B C) ∧ Other ≡ (not A) ∧ C ∧ Other
                replacements = [negate_smt_expression(a), c.strip()]
            elif c_conflicts:
                # (ite A B C) ∧ Other ≡ A ∧ B ∧ Other
                replacements = [a.strip(), b.strip()]
            else:
                new_parts.append(part)
                continue

            new_parts.extend(replacements)
            rewrote_ite = True
            shown = _join_subspec(replacements)
            logger.info(
                f"    [{self.name}] Replaced (ite ...) with {shown[:100]}"
                f"{'...' if len(shown) > 100 else ''}"
            )

        if not rewrote_ite:
            return subspec
        return _join_subspec(new_parts)

    def _split_top_level_conjuncts(self, subspec: str) -> List[str]:
        if _SUBSPEC_SEPARATOR in subspec:
            return _split_subspec(subspec)
        and_args = self._extract_op_args(subspec, "and")
        if and_args is not None and len(and_args) >= 2:
            return and_args
        return [subspec.strip()]

    def _parse_ite(self, expr: str) -> Optional[Tuple[str, str, str]]:
        expr = expr.strip()
        if not expr.startswith("("):
            return None
        end = find_matching_paren(expr, 0)
        if end < 0 or end != len(expr) - 1:
            return None

        inner = expr[1:end]
        i = 0
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i + 3 > len(inner) or inner[i:i + 3] != "ite":
            return None
        # require token boundary after "ite"
        if i + 3 < len(inner) and (inner[i + 3].isalnum() or inner[i + 3] in "!_"):
            return None
        i += 3

        a, i = _extract_next_smt_arg(inner, i)
        b, i = _extract_next_smt_arg(inner, i)
        c, i = _extract_next_smt_arg(inner, i)
        if a is None or b is None or c is None:
            return None
        # reject trailing junk
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i != len(inner):
            return None
        return a, b, c

    def _extract_op_args(self, expr: str, op: str) -> Optional[List[str]]:
        expr = expr.strip()
        if not expr.startswith("("):
            return None
        end = find_matching_paren(expr, 0)
        if end < 0 or end != len(expr) - 1:
            return None
        inner = expr[1:end]
        i = 0
        while i < len(inner) and inner[i].isspace():
            i += 1
        if i + len(op) > len(inner) or inner[i:i + len(op)] != op:
            return None
        # Require token boundary so ">" does not match ">=", "and" not "andx", etc.
        if i + len(op) < len(inner):
            next_ch = inner[i + len(op)]
            if not (next_ch.isspace() or next_ch == "("):
                return None
        i += len(op)
        args: List[str] = []
        while True:
            arg, i = _extract_next_smt_arg(inner, i)
            if arg is None:
                break
            args.append(arg)
        return args

    def _conjuncts_of(self, expr: str) -> List[str]:
        and_args = self._extract_op_args(expr, "and")
        if and_args is not None and len(and_args) >= 1:
            return and_args
        return [expr.strip()]

    @staticmethod
    def _is_var(expr: str) -> bool:
        expr = expr.strip()
        if not expr or any(ch.isspace() for ch in expr):
            return False
        if expr.startswith("(") or expr.startswith("#"):
            return False
        if expr in ("true", "false"):
            return False
        if re.fullmatch(r"-?\d+", expr):
            return False
        return True

    @staticmethod
    def _is_const(expr: str) -> bool:
        expr = expr.strip()
        if expr in ("true", "false"):
            return True
        if re.fullmatch(r"-?\d+", expr):
            return True
        if expr.startswith("#b") or expr.startswith("#x"):
            return True
        return False

    def _try_extract_ground_env(self, branch: str) -> Optional[Dict[str, str]]:
        """Return var->value env if branch is a fully ground conjunction; else None.

        Returns an empty dict only for an empty conjunction; internal contradictions
        are reported via ``_branch_internally_unsat``.
        """
        env: Dict[str, str] = {}

        def assign(var: str, value: str) -> bool:
            var = var.strip()
            value = value.strip()
            if var in env and env[var] != value:
                return False
            env[var] = value
            return True

        for lit in self._conjuncts_of(branch):
            lit = lit.strip()
            if not lit:
                return None
            if lit == "true":
                continue
            if self._is_false_literal(lit):
                return None

            if self._is_var(lit):
                if not assign(lit, "true"):
                    return None
                continue

            not_args = self._extract_op_args(lit, "not")
            if not_args is not None and len(not_args) == 1 and self._is_var(not_args[0]):
                if not assign(not_args[0], "false"):
                    return None
                continue

            eq_args = self._extract_op_args(lit, "=")
            if eq_args is not None and len(eq_args) == 2:
                lhs, rhs = eq_args[0].strip(), eq_args[1].strip()
                if self._is_var(lhs) and self._is_const(rhs):
                    if not assign(lhs, rhs):
                        return None
                    continue
                if self._is_const(lhs) and self._is_var(rhs):
                    if not assign(rhs, lhs):
                        return None
                    continue

            return None

        return env

    def _branch_conflicts_with_others(self, branch: str, other_parts: List[str]) -> bool:
        if self._branch_is_trivially_false(branch):
            return True
        if self._branch_internally_unsat(branch):
            return True
        env = self._try_extract_ground_env(branch)
        if env is None:
            return False

        for other in other_parts:
            result = self._eval_under_env(other, env)
            if result is False:
                return True
        return False

    def _is_false_literal(self, expr: str) -> bool:
        """True for ``false`` or ``(not true)``."""
        expr = expr.strip()
        if expr == "false":
            return True
        not_args = self._extract_op_args(expr, "not")
        if not_args is not None and len(not_args) == 1 and not_args[0].strip() == "true":
            return True
        return False

    def _branch_is_trivially_false(self, branch: str) -> bool:
        """True if branch is propositionally false without needing siblings.

        Handles ``false``, ``(not true)``, and ``(and ... false ...)``.
        """
        branch = branch.strip()
        if self._is_false_literal(branch):
            return True
        for lit in self._conjuncts_of(branch):
            if self._is_false_literal(lit):
                return True
        return False

    def _branch_internally_unsat(self, branch: str) -> bool:
        """True if branch is a ground conjunction with conflicting assignments."""
        if self._branch_is_trivially_false(branch):
            return True
        env: Dict[str, str] = {}
        for lit in self._conjuncts_of(branch):
            lit = lit.strip()
            if self._is_false_literal(lit):
                return True
            if lit == "true":
                continue
            var: Optional[str] = None
            val: Optional[str] = None
            if self._is_var(lit):
                var, val = lit, "true"
            else:
                not_args = self._extract_op_args(lit, "not")
                if not_args is not None and len(not_args) == 1 and self._is_var(not_args[0]):
                    var, val = not_args[0].strip(), "false"
                else:
                    eq_args = self._extract_op_args(lit, "=")
                    if eq_args is not None and len(eq_args) == 2:
                        lhs, rhs = eq_args[0].strip(), eq_args[1].strip()
                        if self._is_var(lhs) and self._is_const(rhs):
                            var, val = lhs, rhs
                        elif self._is_const(lhs) and self._is_var(rhs):
                            var, val = rhs, lhs
            if var is None or val is None:
                return False
            if var in env and env[var] != val:
                return True
            env[var] = val
        return False

    @staticmethod
    def _parse_atomic_value(token: str) -> Optional[Tuple[str, object]]:
        token = token.strip()
        if token == "true":
            return ("bool", True)
        if token == "false":
            return ("bool", False)
        if re.fullmatch(r"-?\d+", token):
            return ("int", int(token))
        if token.startswith("#b"):
            try:
                return ("int", int(token[2:], 2))
            except ValueError:
                return None
        if token.startswith("#x"):
            try:
                return ("int", int(token[2:], 16))
            except ValueError:
                return None
        return None

    def _resolve(self, expr: str, env: Dict[str, str]) -> Optional[Tuple[str, object]]:
        expr = expr.strip()
        if self._is_var(expr) and expr in env:
            return self._parse_atomic_value(env[expr])
        return self._parse_atomic_value(expr)

    @staticmethod
    def _values_equal(
        a: Tuple[str, object], b: Tuple[str, object]
    ) -> bool:
        return a[1] == b[1]

    def _eval_under_env(self, expr: str, env: Dict[str, str]) -> Optional[bool]:
        expr = expr.strip()
        if not expr:
            return None

        resolved = self._resolve(expr, env)
        if resolved is not None and resolved[0] == "bool":
            return bool(resolved[1])
        if self._is_var(expr):
            return None  # unknown boolean var

        # (not X)
        not_args = self._extract_op_args(expr, "not")
        if not_args is not None and len(not_args) == 1:
            inner = self._eval_under_env(not_args[0], env)
            return None if inner is None else (not inner)

        # (and ...)
        and_args = self._extract_op_args(expr, "and")
        if and_args is not None:
            saw_false = False
            saw_unknown = False
            for arg in and_args:
                v = self._eval_under_env(arg, env)
                if v is False:
                    saw_false = True
                elif v is None:
                    saw_unknown = True
            if saw_false:
                return False
            if saw_unknown:
                return None
            return True

        # (or ...)
        or_args = self._extract_op_args(expr, "or")
        if or_args is not None:
            saw_true = False
            saw_unknown = False
            for arg in or_args:
                v = self._eval_under_env(arg, env)
                if v is True:
                    saw_true = True
                elif v is None:
                    saw_unknown = True
            if saw_true:
                return True
            if saw_unknown:
                return None
            return False

        # (ite C T E)
        ite = self._parse_ite(expr)
        if ite is not None:
            cond, t_branch, e_branch = ite
            cv = self._eval_under_env(cond, env)
            if cv is True:
                return self._eval_under_env(t_branch, env)
            if cv is False:
                return self._eval_under_env(e_branch, env)
            return None

        # (= X Y) or comparisons
        for op in ("=", ">=", "<=", ">", "<"):
            args = self._extract_op_args(expr, op)
            if args is None or len(args) != 2:
                continue
            lhs = self._resolve(args[0], env)
            rhs = self._resolve(args[1], env)
            if lhs is None or rhs is None:
                return None
            if op == "=":
                return self._values_equal(lhs, rhs)
            if lhs[0] != "int" or rhs[0] != "int":
                return None
            li, ri = int(lhs[1]), int(rhs[1])  # type: ignore[arg-type]
            if op == ">=":
                return li >= ri
            if op == "<=":
                return li <= ri
            if op == ">":
                return li > ri
            if op == "<":
                return li < ri

        return None


class ConstraintRedundancyEliminationRule(NormalizationRule):
    """Evaluate destination-prefix constraints under an explicit target prefix."""

    def __init__(self, enabled: bool = True, target_dst_ip: Optional[str] = None):
        super().__init__("Constraint Redundancy Elimination", enabled=enabled)
        self.target_dst_ip = target_dst_ip
        self.target_dst_ip_constraint = None
        self.target_dst_ip_network = None
        if target_dst_ip:
            self.target_dst_ip_constraint = (
                self._construct_target_dst_ip_constraint(target_dst_ip)
            )
            try:
                import ipaddress

                self.target_dst_ip_network = ipaddress.ip_network(
                    target_dst_ip, strict=False
                )
            except (ValueError, ImportError):
                pass

    def _construct_target_dst_ip_constraint(
        self, ip_mask: str
    ) -> Optional[_ExtractConstraint]:
        """Return the extract equality represented by an IPv4 prefix."""
        result = prefix_string_to_constraint_tuple(ip_mask)
        if not result:
            logger.warning(f"    [{self.name}] Failed to parse target_dst_ip '{ip_mask}'")
            return None

        return result

    @staticmethod
    def _parse_hex_value(val_str: str) -> Optional[int]:
        try:
            if val_str.startswith('#x'):
                return int(val_str[2:], 16)
            if val_str.startswith('0x'):
                return int(val_str[2:], 16)
            if val_str.startswith('#b'):
                return int(val_str[2:], 2)
            return None
        except (ValueError, AttributeError):
            return None

    def _evaluate_constraint(
        self,
        constraint: _ExtractConstraint,
        key_target: _ExtractConstraint,
    ) -> Optional[bool]:
        """Evaluate a constraint against key target using prefix comparison logic

        Logic:
        - Case 1/2: other prefix_length < target prefix_length
          - Compare first other_prefix_length bits (use other prefix length)
          - If same -> True (case1)
          - If different -> False (case2)
        - Case 3/4: other prefix_length = target prefix_length
          - Compare directly (same length)
          - If same -> None (keep unchanged, case4)
          - If different -> False (case3)
        - Case 5/6: other prefix_length > target prefix_length
          - Compare first target_prefix_length bits (use target prefix length)
          - If same -> None (cannot determine, case6)
          - If different -> False (case5)

        Args:
            constraint: (high_bit, low_bit, variable, value) to evaluate
            key_target: (high_bit, low_bit, variable, value) key target constraint

        Returns:
            True if constraint is compatible with key target
            False if constraint contradicts key target
            None if cannot determine or should keep unchanged
        """
        high1, low1, var1, val1 = constraint
        high2, low2, var2, val2 = key_target

        # Must be same variable
        if var1 != var2:
            return None

        # Both must start at the same high bit (31 for IPv4)
        if high1 != high2 or high1 != 31:
            return None

        other_prefix_length = 32 - low1
        target_prefix_length = 32 - low2

        val1_int = self._parse_hex_value(val1)
        val2_int = self._parse_hex_value(val2)

        if val1_int is None or val2_int is None:
            return None

        if other_prefix_length == target_prefix_length:
            if val1_int == val2_int:
                return None
            return False

        if other_prefix_length < target_prefix_length:
            shift_amount = target_prefix_length - other_prefix_length
            target_prefix_bits = (val2_int >> shift_amount) & (
                (1 << other_prefix_length) - 1
            )
            other_prefix_bits = val1_int & ((1 << other_prefix_length) - 1)
            return other_prefix_bits == target_prefix_bits

        shift_amount = other_prefix_length - target_prefix_length
        other_prefix_bits = (val1_int >> shift_amount) & (
            (1 << target_prefix_length) - 1
        )
        target_prefix_bits = val2_int & ((1 << target_prefix_length) - 1)
        return None if other_prefix_bits == target_prefix_bits else False

    def _find_all_extract_constraints(
        self, expr: str
    ) -> List[_LocatedExtractConstraint]:
        """Return extract equalities with source positions and parsed fields."""
        constraints = []
        for match in _EXTRACT_CONSTRAINT_RE.finditer(expr):
            start_pos = match.start()
            constraint_str = match.group(0)
            high_bit = int(match.group(1))
            low_bit = int(match.group(2))
            variable = match.group(3).strip()
            value = match.group(4).strip()
            constraints.append((start_pos, constraint_str, (high_bit, low_bit, variable, value)))

        return constraints

    def _same_extract_constraint(
        self,
        left: _ExtractConstraint,
        right: _ExtractConstraint,
    ) -> bool:
        left_high, left_low, left_var, left_value = left
        right_high, right_low, right_var, right_value = right
        return (
            left_high == right_high
            and left_low == right_low
            and left_var == right_var
            and self._parse_hex_value(left_value)
            == self._parse_hex_value(right_value)
        )

    def _has_positive_top_level_target(
        self,
        subspec: str,
        target: _ExtractConstraint,
    ) -> bool:
        """Return whether the target equality is an explicit top-level conjunct."""
        for part in _split_subspec(subspec):
            constraints = self._find_all_extract_constraints(part)
            if len(constraints) != 1:
                continue
            start, constraint_text, constraint = constraints[0]
            if (
                start == 0
                and len(constraint_text) == len(part)
                and self._same_extract_constraint(constraint, target)
            ):
                return True
        return False

    def _replace_constraint_smart(
        self,
        expr: str,
        constraint_str: str,
        start_pos: int,
        replacement: str,
    ) -> str:
        """Replace an equality or its immediately enclosing negation."""
        if start_pos >= 3 and expr[start_pos-4:start_pos] == "(not":
            not_start = start_pos - 4
            not_end = find_matching_paren(expr, not_start)
            if not_end > 0:
                opposite = "false" if replacement == "true" else "true"
                return expr[:not_start] + opposite + expr[not_end+1:]

        return expr[:start_pos] + replacement + expr[start_pos + len(constraint_str):]

    def apply(self, subspec: str, context: Optional[Dict] = None) -> str:
        if not self.enabled:
            return subspec

        if not self.target_dst_ip_constraint:
            return subspec

        high, low, var, val = self.target_dst_ip_constraint
        logger.debug(
            f"    [{self.name}] Using target_dst_ip constraint: "
            f"extract {high} {low} = {val}"
        )

        key_target = self.target_dst_ip_constraint
        all_constraints = self._find_all_extract_constraints(subspec)

        if not all_constraints:
            return subspec

        if not self._has_positive_top_level_target(subspec, key_target):
            logger.debug(
                "Target dst-ip equality is not a positive top-level conjunct; "
                "skipping prefix simplification"
            )
            return subspec

        result = subspec
        changes_made = False

        # Reverse traversal keeps recorded source positions valid after replacement.
        for start_pos, constraint_str, constraint in reversed(all_constraints):
            high, low, var, val = constraint

            key_var = key_target[2]
            if var != key_var:
                continue

            # Keep the explicit target assumption in the normalized subspec.
            if self._same_extract_constraint(constraint, key_target):
                continue

            evaluation = self._evaluate_constraint(constraint, key_target)

            if evaluation is True:
                result = self._replace_constraint_smart(
                    result, constraint_str, start_pos, "true"
                )
                changes_made = True
                logger.debug(
                    f"    [{self.name}] Simplified compatible constraint "
                    f"to true: {constraint_str}"
                )
            elif evaluation is False:
                result = self._replace_constraint_smart(
                    result, constraint_str, start_pos, "false"
                )
                changes_made = True
                logger.debug(
                    f"    [{self.name}] Simplified contradicting constraint "
                    f"to false: {constraint_str}"
                )

        if changes_made:
            logger.info(
                f"    [{self.name}] Applied constraint redundancy "
                "elimination using key targets"
            )

        return result


class NormalizationRuleManager:
    """Apply an ordered collection of normalization rules."""

    def __init__(self, rules: Optional[List[NormalizationRule]] = None):
        self.rules = [] if rules is None else rules

    def add_rule(self, rule: NormalizationRule) -> None:
        self.rules.append(rule)
        logger.info(f"Added normalization rule: {rule}")

    def remove_rule(self, rule_name: str) -> None:
        self.rules = [r for r in self.rules if r.name != rule_name]
        logger.info(f"Removed normalization rule: {rule_name}")

    def enable_rule(self, rule_name: str) -> None:
        for rule in self.rules:
            if rule.name == rule_name:
                rule.enabled = True
                logger.info(f"Enabled rule: {rule_name}")
                return
        logger.warning(f"Rule not found: {rule_name}")

    def disable_rule(self, rule_name: str) -> None:
        for rule in self.rules:
            if rule.name == rule_name:
                rule.enabled = False
                logger.info(f"Disabled rule: {rule_name}")
                return
        logger.warning(f"Rule not found: {rule_name}")

    def apply_all(self, subspec: str, context: Optional[Dict] = None) -> str:
        """Apply enabled rules in order and fail at the first invalid result."""
        result = subspec

        for rule in self.rules:
            if rule.enabled:
                try:
                    result = rule.apply(result, context)
                except Exception as exc:
                    raise RuntimeError(
                        f"Failed to apply normalization rule {rule.name}: {exc}"
                    ) from exc

        return result

    def get_rules_info(self) -> List[Dict]:
        return [
            {
                "name": rule.name,
                "class": rule.__class__.__name__,
                "enabled": rule.enabled,
            }
            for rule in self.rules
        ]


# Fixed rule pipelines.


def normalizer1(subspec: str, target_dst_ip: Optional[str] = None) -> str:
    """Apply pre-Z3 semantic simplifications in their fixed order."""
    rules = [
        ComparisonOperatorNormalizationRule(),
        IteEqualitySimplificationRule(),
        ConstraintRedundancyEliminationRule(target_dst_ip=target_dst_ip),
        IteBranchConflictSimplificationRule(),
    ]

    return NormalizationRuleManager(rules).apply_all(subspec)


def normalizer2(subspec: str) -> str:
    """Apply the fixed final-pass normalization rules."""
    rules = [
        LetExpressionExpansionRule(),
        ComparisonConstraintReorderingRule(),
        RedundantComparisonEliminationRule(),
        BitwiseDeMorganRule(),
        LogicalDeMorganRule(),
        IteBranchConflictSimplificationRule(),
    ]

    return NormalizationRuleManager(rules).apply_all(subspec)


# Iterative Z3 orchestration.


@dataclass(frozen=True)
class _Z3NormalizationContext:
    metadata_file: Path
    config_name: str
    declares: List[str]
    commented_equalities: List[str]
    config_names: Set[str]
    check_all_configs: bool
    device: Optional[str]
    temp_dir: Optional[Path]


def normalize_subspec(
    subspec: str,
    metadata_file: Path,
    config_name: str,
    is_field_level: bool = True,
    is_pair: bool = False,
    target_dst_ip: Optional[str] = None,
    max_iterations: int = util_keyword.SUBSPEC_NORM_COUNT,
    verbose: bool = False,
    temp_dir: Optional[Path] = None,
    config_names: Optional[Set[str]] = None,
) -> str:
    """Normalize one subspec through local rules and iterative Z3 simplification."""
    if subspec == "empty" or not subspec.strip():
        return subspec

    declares, commented_equalities, device = util_file.load_synthesis_metadata_file(
        metadata_file
    )
    if not declares:
        logger.warning(
            f"No declares found in metadata file {metadata_file}, "
            "returning original subspec"
        )
        return subspec

    scoped_config_names, check_all_configs = _select_config_scope(
        config_name,
        commented_equalities,
        is_field_level=is_field_level,
        is_pair=is_pair,
        config_names=config_names,
    )
    context = _Z3NormalizationContext(
        metadata_file=metadata_file,
        config_name=config_name,
        declares=declares,
        commented_equalities=commented_equalities,
        config_names=scoped_config_names,
        check_all_configs=check_all_configs,
        device=device,
        temp_dir=temp_dir,
    )

    base_subspec, community_suffix = _strip_community_suffix(subspec)
    normalized = _normalize_base_subspec(
        base_subspec,
        target_dst_ip=target_dst_ip,
        max_iterations=max_iterations,
        verbose=verbose,
        context=context,
    )
    return _merge_community_suffix(normalized, community_suffix)


def _select_config_scope(
    config_name: str,
    commented_equalities: List[str],
    *,
    is_field_level: bool,
    is_pair: bool,
    config_names: Optional[Set[str]],
) -> Tuple[Set[str], bool]:
    """Return target Config variables and whether all must survive extraction."""
    if config_names is not None:
        return set(config_names), True
    if not is_field_level:
        return _extract_config_vars_from_commented_equalities(
            commented_equalities
        ), True
    if is_pair:
        return _get_pair_config_names(config_name), True
    return {config_name}, False


def _normalize_base_subspec(
    subspec: str,
    *,
    target_dst_ip: Optional[str],
    max_iterations: int,
    verbose: bool,
    context: _Z3NormalizationContext,
) -> str:
    """Run the existing let, local-rule, Z3, and final-rule sequence."""
    # Expand lets once before the n1/Z3 loop so bare (ite ...) is visible to n1.
    # normalizer1 itself never expands lets; normalizer2 expands again at the end.
    current_subspec = LetExpressionExpansionRule().apply(subspec)
    if verbose and current_subspec != subspec:
        logger.info(
            "Expanded let expressions once before normalizer1 loop for "
            f"{context.config_name}"
        )
    previous_z3_result: Optional[str] = None
    after_normalizer1 = current_subspec

    for iteration in range(max_iterations):
        if verbose:
            logger.info(
                f"Normalizing {context.config_name}, iteration "
                f"{iteration + 1}/{max_iterations}"
            )

        after_normalizer1 = normalizer1(
            current_subspec, target_dst_ip=target_dst_ip
        )
        if after_normalizer1 == current_subspec:
            if iteration == 0 and after_normalizer1 == subspec:
                previous_z3_result = after_normalizer1
            break

        z3_result = _simplify_with_z3(
            after_normalizer1,
            context,
            iteration + 1,
            original_subspec=after_normalizer1,
        )
        converged = (
            z3_result == previous_z3_result
            or z3_result == after_normalizer1
        )
        previous_z3_result = z3_result
        current_subspec = z3_result
        if converged:
            break

    final_input = previous_z3_result if previous_z3_result else after_normalizer1
    final_after_normalizer1 = normalizer1(
        final_input, target_dst_ip=target_dst_ip
    )
    return normalizer2(final_after_normalizer1)


def _extract_config_vars_from_commented_equalities(
    commented_equalities: List[str],
) -> Set[str]:
    config_vars = set()
    for eq in commented_equalities:
        match = re.search(_CONFIG_VARIABLE_PATTERN, eq)
        if match:
            config_vars.add(match.group(0))
    return config_vars


def _get_pair_config_names(config_name: str) -> Set[str]:
    if config_name.endswith("__ip"):
        return {config_name, config_name[:-4] + "__mask"}
    if config_name.endswith("__mask"):
        return {config_name[:-6] + "__ip", config_name}
    return {config_name}


def _commented_equalities_for_configs(
    commented_equalities: List[str],
    config_names: Set[str],
    *,
    original_subspec: Optional[str] = None,
) -> List[str]:
    """Filter commented ``(assert (= Config ...))`` to ``config_names``.

    When ``original_subspec`` is set, only keep equalities whose Config_* also
    appears in that subspec — avoids joint metadata (all commented enables)
    replacing an unrelated group's constraints.
    """
    result_parts: List[str] = []
    for eq in commented_equalities:
        match = re.search(_CONFIG_VARIABLE_PATTERN, eq)
        if not match or match.group(0) not in config_names or "(= " not in eq:
            continue
        name = match.group(0)
        if original_subspec is not None and name not in original_subspec:
            continue
        m = re.match(r"\(assert\s+(.+)\)", eq)
        result_parts.append(
            m.group(1) if m else eq.replace("(assert ", "").rstrip(")")
        )
    return result_parts


def _extract_config_constraints_from_z3_output(
    z3_output: str,
    config_names: Set[str],
    commented_equalities: List[str],
    check_all_configs: bool = False,
    original_subspec: Optional[str] = None,
) -> str:
    constraint_parts = extract_smt_goal_dependency_closure(
        z3_output, config_names
    )
    found_config_vars = set()
    for constraint in constraint_parts:
        found_config_vars.update(
            config_name
            for config_name in config_names
            if re.search(
                rf"(?<![a-zA-Z0-9_-]){re.escape(config_name)}(?![a-zA-Z0-9_-])",
                constraint,
            )
        )
    # A ground goal must not suppress the baseline fallback when solve-eqs has
    # eliminated every target Config variable.
    if check_all_configs or not found_config_vars:
        missing_configs = config_names - found_config_vars
        if missing_configs:
            constraint_parts.extend(
                _commented_equalities_for_configs(
                    commented_equalities,
                    missing_configs,
                    original_subspec=original_subspec,
                )
            )
    if constraint_parts:
        return _join_subspec(constraint_parts)
    # Fall back to equality constraints when no goal content mentioned config names.
    # Only for configs that appear in the original subspec (joint-safe).
    parts = _commented_equalities_for_configs(
        commented_equalities, config_names, original_subspec=original_subspec
    )
    return _join_subspec(parts) if parts else ""


def _simplify_with_z3(
    subspec: str,
    context: _Z3NormalizationContext,
    iteration: int,
    *,
    original_subspec: Optional[str] = None,
) -> str:
    if subspec == "empty" or not subspec.strip():
        return subspec
    operation = (
        f"normalization of {context.config_name} on device "
        f"{context.device or 'unknown'} "
        f"at iteration {iteration}"
    )
    smt_input = build_smt_simplification_input(
        subspec,
        config_name=context.config_name,
        declares=context.declares,
        iteration=iteration,
    )
    if not smt_input:
        raise ValueError(f"Failed to build SMT input for {operation}")
    util_file.write_normalization_smt_input(
        smt_input,
        metadata_file=context.metadata_file,
        config_name=context.config_name,
        iteration=iteration,
        device=context.device,
        output_dir=context.temp_dir,
    )
    try:
        result = run_z3_text(smt_input)
    except Exception as exc:
        raise RuntimeError(f"Failed to run Z3 for {operation}: {exc}") from exc
    output = require_successful_z3_output(result, operation)
    try:
        simplified = _extract_config_constraints_from_z3_output(
            output,
            context.config_names,
            context.commented_equalities,
            check_all_configs=context.check_all_configs,
            original_subspec=(
                original_subspec if original_subspec is not None else subspec
            ),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to parse Z3 output for {operation}: {exc}"
        ) from exc
    return simplified if simplified else subspec


def _strip_community_suffix(subspec: str) -> Tuple[str, Optional[str]]:
    for pattern in _COMMUNITY_SUFFIX_RES:
        match = pattern.search(subspec)
        if match:
            base_subspec = _TRAILING_AND_RE.sub(
                "", subspec[:match.start()].strip()
            )
            return base_subspec, subspec[match.start():].strip()
    return subspec, None


def _merge_community_suffix(
    base_subspec: str, community_suffix: Optional[str]
) -> str:
    return f"{base_subspec} {community_suffix}" if community_suffix else base_subspec
