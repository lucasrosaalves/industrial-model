from __future__ import annotations

import ast
import functools
import math
import re
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from ._evaluator import _BINARY_OPS, _UNARY_OPS
from ._functions import ALLOWED_FUNCTIONS, BUCKET_AGGREGATES
from ._types import BucketAggregate
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


_SAFE_BUCKET_PREFIX = "__formula_expression_bucket_"


@dataclass(frozen=True, slots=True)
class CompiledFormula:
    raw: str
    expression: str
    # With ``bucket_terms`` set, this is the per-bucket formula: each
    # ``sum(...)`` / ``average(...)`` call is replaced by its term's ``key``,
    # and ``variables`` / ``name_map`` hold those keys next to the
    # placeholders referenced outside any call.
    tree: ast.Expression
    variables: tuple[str, ...]
    name_map: Mapping[str, str]
    has_conditional: bool
    bucket_terms: tuple[BucketTerm, ...] = ()


@dataclass(frozen=True, slots=True)
class BucketTerm:
    """One ``sum(...)`` / ``average(...)`` call of a bucket formula.

    ``formula`` is the call's argument, which runs per aligned point; its
    results are aggregated into buckets by ``aggregate``. The per-bucket
    formula reads those bucket values under ``key``, which can never clash
    with a placeholder name.
    """

    aggregate: BucketAggregate
    key: str
    formula: CompiledFormula


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
    if not any(_is_call_to(node, BUCKET_AGGREGATES) for node in ast.walk(tree)):
        return _finish(raw, expression, tree.body, name_map)
    return _compile_bucket_formula(raw, expression, tree.body, name_map)


def _finish(
    raw: str,
    expression: str,
    body: ast.expr,
    name_map: Mapping[str, str],
    bucket_terms: tuple[BucketTerm, ...] = (),
) -> CompiledFormula:
    tree = ast.Expression(body=body)
    has_conditional = any(
        isinstance(node, _CONDITIONAL_NODES) for node in ast.walk(tree)
    )
    tree = ast.Expression(body=_fold_constants(tree.body))
    _validate_folded_function_args(tree)
    return CompiledFormula(
        raw=raw,
        expression=expression,
        tree=tree,
        variables=tuple(name_map),
        name_map=name_map,
        has_conditional=has_conditional,
        bucket_terms=bucket_terms,
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


def _compile_bucket_formula(
    raw: str,
    expression: str,
    body: ast.expr,
    name_map: Mapping[str, str],
) -> CompiledFormula:
    """Split a formula into per-point bucket terms and a per-bucket formula.

    Every ``sum(...)`` / ``average(...)`` call becomes a :class:`BucketTerm`
    and is replaced by a name the per-bucket formula reads its bucket values
    by. Identical calls share one term.
    """

    extractor = _BucketTermExtractor()
    body = extractor.visit(body)
    for node in ast.walk(body):
        if _is_call_to(node, ALLOWED_FUNCTIONS):
            raise InvalidFormulaError(
                f"{_call_name(node)}() cannot be combined with sum() / average() yet"
            )

    terms: list[BucketTerm] = []
    for index, (aggregate, argument) in enumerate(extractor.calls):
        used = _names_in(argument)
        term_names = {name: safe for name, safe in name_map.items() if safe in used}
        if not term_names:
            raise InvalidFormulaError(
                f"{aggregate}() must reference at least one parameter"
            )
        per_point = _finish(raw, ast.unparse(argument), argument, term_names)
        terms.append(BucketTerm(aggregate, f"{aggregate}#{index}", per_point))

    used = _names_in(body)
    outer_names = {name: safe for name, safe in name_map.items() if safe in used}
    for index, term in enumerate(terms):
        outer_names[term.key] = f"{_SAFE_BUCKET_PREFIX}{index}"
    return _finish(raw, expression, body, outer_names, tuple(terms))


class _BucketTermExtractor(ast.NodeTransformer):
    """Replace each ``sum(...)`` / ``average(...)`` call by a term name."""

    def __init__(self) -> None:
        self.calls: list[tuple[BucketAggregate, ast.expr]] = []
        self._indexes: dict[tuple[str, str], int] = {}

    def visit_Call(self, node: ast.Call) -> ast.AST:
        if not _is_call_to(node, BUCKET_AGGREGATES):
            return self.generic_visit(node)
        aggregate = cast(BucketAggregate, _call_name(node))
        argument = node.args[0]
        for inner in ast.walk(argument):
            if _is_call_to(inner, BUCKET_AGGREGATES):
                raise InvalidFormulaError("sum() and average() cannot be nested")
            if _is_call_to(inner, ALLOWED_FUNCTIONS):
                raise InvalidFormulaError(
                    f"{aggregate}() cannot wrap {_call_name(inner)}() yet"
                )
        signature = (aggregate, ast.dump(argument))
        index = self._indexes.get(signature)
        if index is None:
            index = len(self.calls)
            self._indexes[signature] = index
            self.calls.append((aggregate, argument))
        return ast.copy_location(
            ast.Name(id=f"{_SAFE_BUCKET_PREFIX}{index}", ctx=ast.Load()), node
        )


def _is_call_to(node: ast.AST, names: Collection[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in names
    )


def _call_name(node: ast.AST) -> str:
    assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    return node.func.id


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _validate_call_shape(node: ast.Call) -> None:
    if not isinstance(node.func, ast.Name):
        raise InvalidFormulaError(
            f"unsupported formula element: {type(node.func).__name__}"
        )

    if node.func.id in BUCKET_AGGREGATES:
        arity = 1
    else:
        spec = ALLOWED_FUNCTIONS.get(node.func.id)
        if spec is None:
            if node.func.id.startswith(_SAFE_NAME_PREFIX):
                raise InvalidFormulaError("unsupported formula element: Call")
            raise InvalidFormulaError(f"unknown formula function: {node.func.id}")
        arity = spec.arity

    if node.keywords:
        raise InvalidFormulaError(f"{node.func.id}() does not accept keyword arguments")
    if any(isinstance(arg, ast.Starred) for arg in node.args):
        raise InvalidFormulaError(f"{node.func.id}() does not accept starred arguments")
    if len(node.args) != arity:
        noun = "argument" if arity == 1 else "arguments"
        raise InvalidFormulaError(
            f"{node.func.id}() takes {arity} {noun}, got {len(node.args)}"
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
