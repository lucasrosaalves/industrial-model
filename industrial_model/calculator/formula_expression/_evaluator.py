from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import TypeAlias

_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_pow(base: float, exponent: float) -> float:
    # Always exponentiate in float space. ``operator.pow`` on two large ints
    # (e.g. ``10 ** 100000000``) would build an enormous integer and can hang
    # the process, whereas float exponentiation overflows quickly with a cheap
    # ``OverflowError``. Constant folding already coerces operands here, so this
    # closes the only path that received raw integer constants.
    return float(float(base) ** float(exponent))


_BINARY_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: _safe_pow,
    ast.Mod: operator.mod,
}

# A value is either a single scalar (broadcast across the whole series) or an
# already-materialized per-element sequence. Keeping constant operands as
# scalars avoids allocating length-N tuples for them and skips the element-wise
# zip whenever one side of an operation is constant.
Value: TypeAlias = float | tuple[float, ...]


def evaluate_tree(
    tree: ast.Expression,
    environment: dict[str, tuple[float, ...]],
    *,
    length: int,
) -> tuple[float, ...]:
    result = _evaluate_node(tree.body, environment)
    if isinstance(result, tuple):
        return result
    # The compiler guarantees at least one parameter, so a scalar result only
    # happens for degenerate trees; broadcast it to the series length.
    return (result,) * length


def _evaluate_node(node: ast.AST, environment: dict[str, tuple[float, ...]]) -> Value:
    if isinstance(node, ast.Name):
        return environment[node.id]

    if isinstance(node, ast.Constant):
        # _validate_tree ensures constants are non-bool int or float.
        assert isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        return float(node.value)

    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, environment)
        right = _evaluate_node(node.right, environment)
        return _apply_binary(_BINARY_OPS[type(node.op)], left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand, environment)
        op = _UNARY_OPS[type(node.op)]
        if isinstance(operand, tuple):
            return tuple(op(value) for value in operand)
        return op(operand)

    msg = f"unsupported formula element: {type(node).__name__}"
    raise TypeError(msg)


def _apply_binary(
    op: Callable[[float, float], float], left: Value, right: Value
) -> Value:
    if isinstance(left, tuple):
        if isinstance(right, tuple):
            return tuple(op(lv, rv) for lv, rv in zip(left, right, strict=True))
        return tuple(op(lv, right) for lv in left)
    if isinstance(right, tuple):
        return tuple(op(left, rv) for rv in right)
    return op(left, right)
