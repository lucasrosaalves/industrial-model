from __future__ import annotations

import ast
import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from ._evaluator import _BINARY_OPS, _UNARY_OPS
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


@dataclass(frozen=True, slots=True)
class CompiledFormula:
    raw: str
    expression: str
    tree: ast.Expression
    variables: tuple[str, ...]
    name_map: Mapping[str, str]


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
    tree = ast.Expression(body=_fold_constants(tree.body))
    return CompiledFormula(
        raw=raw,
        expression=expression,
        tree=tree,
        variables=tuple(variables),
        name_map=name_map,
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
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES + _ALLOWED_OPERATORS):
            raise InvalidFormulaError(
                f"unsupported formula element: {type(node).__name__}"
            )

        if isinstance(node, ast.Name) and node.id not in allowed_names:
            raise InvalidFormulaError(f"unknown formula identifier: {node.id}")

        if isinstance(node, ast.Constant) and (
            isinstance(node.value, bool) or not isinstance(node.value, (int, float))
        ):
            raise InvalidFormulaError("only numeric constants are supported")


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

    return node
