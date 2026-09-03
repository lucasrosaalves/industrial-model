from __future__ import annotations

import ast
import functools
import math
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from ._evaluator import _BINARY_OPS, _UNARY_OPS
from ._functions import ALLOWED_FUNCTIONS
from .exceptions import InvalidFormulaError

_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_UNRESOLVED_BRACE_RE = re.compile(r"[{}]")
_SAFE_NAME_PREFIX = "__formula_expression_param_"

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.IfExp,
    ast.Compare,
    ast.BoolOp,
    ast.Call,
)
_ALLOWED_OPERATORS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.UAdd,
    ast.USub,
)
_ALLOWED_COMPARE_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)
_ALLOWED_BOOL_OPS = (
    ast.And,
    ast.Or,
)
_CONDITIONAL_NODES = (ast.IfExp, ast.Compare, ast.BoolOp)


@dataclass(frozen=True, slots=True)
class CompiledFormula:
    raw: str
    expression: str
    tree: ast.Expression
    variables: tuple[str, ...]
    name_map: Mapping[str, str]
    has_conditional: bool


@lru_cache(maxsize=1024)
def _compile_normalized(raw: str) -> CompiledFormula:
    if not raw:
        raise InvalidFormulaError("formula must not be empty")

    variables: list[str] = []
    name_map: dict[str, str] = {}
    expression = _replace_placeholders(raw, variables, name_map)

    if not variables:
        raise InvalidFormulaError("formula must reference at least one parameter")

    if _UNRESOLVED_BRACE_RE.search(expression):
        raise InvalidFormulaError("formula contains invalid placeholder syntax")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise InvalidFormulaError(f"invalid formula syntax: {exc.msg}") from exc

    _validate_tree(tree, set(name_map.values()))
    has_conditional = any(
        isinstance(node, _CONDITIONAL_NODES) for node in ast.walk(tree)
    )
    tree = ast.Expression(body=_fold_constants(tree.body))
    _validate_folded_function_args(tree)
    return CompiledFormula(
        raw=raw,
        expression=expression,
        tree=tree,
        variables=tuple(variables),
        name_map=name_map,
        has_conditional=has_conditional,
    )


class _FormulaCompiler:
    """Normalizes the formula text, then delegates to the lru_cache'd compiler."""

    def __call__(self, formula: str) -> CompiledFormula:
        return _compile_normalized(_normalize_formula_text(formula))

    def cache_clear(self) -> None:
        _compile_normalized.cache_clear()

    def cache_info(self) -> functools._CacheInfo:
        return _compile_normalized.cache_info()


# Expose the underlying cache controls on the public entry point so callers can
# inspect or clear the compilation cache via ``compile_formula``.
compile_formula = _FormulaCompiler()


def _normalize_formula_text(formula: object) -> str:
    if not isinstance(formula, str):
        raise TypeError("formula must be a string")
    return " ".join(formula.split())


def _replace_placeholders(
    formula: str,
    variables: list[str],
    name_map: dict[str, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in name_map:
            name_map[name] = f"{_SAFE_NAME_PREFIX}{len(name_map)}"
            variables.append(name)
        return name_map[name]

    return _PLACEHOLDER_RE.sub(replace, formula)


def _validate_tree(tree: ast.Expression, allowed_names: set[str]) -> None:
    function_name_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            _validate_call_shape(node)
            function_name_nodes.add(id(node.func))

        if not isinstance(
            node,
            _ALLOWED_AST_NODES
            + _ALLOWED_OPERATORS
            + _ALLOWED_COMPARE_OPS
            + _ALLOWED_BOOL_OPS,
        ):
            raise InvalidFormulaError(
                f"unsupported formula element: {type(node).__name__}"
            )

        if (
            isinstance(node, ast.Name)
            and id(node) not in function_name_nodes
            and node.id not in allowed_names
        ):
            raise InvalidFormulaError(f"unknown formula identifier: {node.id}")

        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise InvalidFormulaError("only numeric constants are supported")


def _validate_call_shape(node: ast.Call) -> None:
    if not isinstance(node.func, ast.Name):
        raise InvalidFormulaError(
            f"unsupported formula element: {type(node.func).__name__}"
        )

    spec = ALLOWED_FUNCTIONS.get(node.func.id)
    if spec is None:
        if node.func.id.startswith(_SAFE_NAME_PREFIX):
            raise InvalidFormulaError("unsupported formula element: Call")
        raise InvalidFormulaError(f"unknown formula function: {node.func.id}")

    if node.keywords:
        raise InvalidFormulaError(f"{node.func.id}() does not accept keyword arguments")
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        raise InvalidFormulaError(f"{node.func.id}() does not accept starred arguments")
    if len(node.args) != spec.arity:
        raise InvalidFormulaError(
            f"{node.func.id}() takes {spec.arity} arguments, got {len(node.args)}"
        )


def _validate_folded_function_args(tree: ast.Expression) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        spec = ALLOWED_FUNCTIONS.get(node.func.id)
        if spec is None or spec.window_arg is None:
            continue
        window_node = node.args[spec.window_arg]
        if not isinstance(window_node, ast.Constant):
            raise InvalidFormulaError(
                f"{node.func.id}() window must be a numeric constant"
            )
        if _to_positive_int_window(window_node.value) is None:
            raise InvalidFormulaError(
                f"{node.func.id}() window must be a positive integer"
            )


def _to_positive_int_window(value: object) -> int | None:
    """Return ``N`` when ``value`` is a positive integer, including float noise.

    Folded expressions such as ``8.3 - 5.3`` are not always exact integers
    (they land a few ULPs away). Accept those and reject true non-integers
    such as ``1.5``.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    if not math.isfinite(value) or value < 1:
        return None
    rounded = round(value)
    if rounded < 1:
        return None
    tolerance = sys.float_info.epsilon * max(1.0, abs(value)) * 16
    if abs(value - rounded) <= tolerance:
        return int(rounded)
    return None


def _fold_constants(node: ast.expr) -> ast.expr:
    """Collapse constant-only subtrees to a single constant at compile time.

    This runs once per formula (results are cached) so sub-expressions like
    ``24 * 3600`` or ``0.453592`` are not recomputed on every evaluation. A fold
    that raises (e.g. division by zero) is skipped so the original runtime error
    semantics are preserved.
    """

    if isinstance(node, ast.BinOp):
        node.left = _fold_constants(node.left)
        node.right = _fold_constants(node.right)
        if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
            try:
                value = _BINARY_OPS[type(node.op)](
                    cast(float, node.left.value),
                    cast(float, node.right.value),
                )
            except ArithmeticError:
                return node
            return ast.copy_location(ast.Constant(value=value), node)
        return node

    if isinstance(node, ast.UnaryOp):
        node.operand = _fold_constants(node.operand)
        if isinstance(node.operand, ast.Constant):
            value = _UNARY_OPS[type(node.op)](cast(float, node.operand.value))
            return ast.copy_location(ast.Constant(value=value), node)
        return node

    # Conditional/comparison nodes are never collapsed to a single constant:
    # doing so could fold a boolean result (rejected everywhere else as a
    # constant type) and, worse, could eagerly evaluate a branch that runtime
    # short-circuiting is meant to skip (e.g. the ``else`` side of a
    # division-by-zero guard). Only their constant-only sub-expressions are
    # folded.
    if isinstance(node, ast.IfExp):
        node.test = _fold_constants(node.test)
        node.body = _fold_constants(node.body)
        node.orelse = _fold_constants(node.orelse)
        return node

    if isinstance(node, ast.Compare):
        node.left = _fold_constants(node.left)
        node.comparators = [_fold_constants(c) for c in node.comparators]
        return node

    if isinstance(node, ast.BoolOp):
        node.values = [_fold_constants(v) for v in node.values]
        return node

    if isinstance(node, ast.Call):
        node.args = [_fold_constants(arg) for arg in node.args]
        return _fold_call_window_arg(node)

    return node


def _fold_call_window_arg(node: ast.Call) -> ast.Call:
    """Rewrite a near-integer folded window to an exact int.

    Keeps later evaluation from depending on ``int(2.999…)`` truncating.
    """

    if not isinstance(node.func, ast.Name):
        return node
    spec = ALLOWED_FUNCTIONS.get(node.func.id)
    if spec is None or spec.window_arg is None:
        return node
    window_node = node.args[spec.window_arg]
    if not isinstance(window_node, ast.Constant):
        return node
    integer = _to_positive_int_window(window_node.value)
    if integer is None or integer == window_node.value:
        return node
    node.args[spec.window_arg] = ast.copy_location(
        ast.Constant(value=integer), window_node
    )
    return node
