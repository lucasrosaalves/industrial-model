from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import TypeAlias

from ._functions import ALLOWED_FUNCTIONS, FunctionSpec

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

_COMPARE_OPS: dict[type[ast.cmpop], Callable[[float, float], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
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
    has_conditional: bool = False,
) -> tuple[float, ...]:
    if has_conditional:
        # ``if``/``else`` branches must only be evaluated for the elements that
        # select them (e.g. a division-by-zero guard's ``else`` branch must
        # never run for elements where the guarded division is safe). This
        # requires evaluating index-by-index instead of the whole-series
        # vectorized path below.
        return tuple(
            _evaluate_node_at(tree.body, environment, index) for index in range(length)
        )

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

    if isinstance(node, ast.Call):
        return _evaluate_call(node, environment)

    msg = f"unsupported formula element: {type(node).__name__}"
    raise TypeError(msg)


def _evaluate_node_at(
    node: ast.AST, environment: dict[str, tuple[float, ...]], index: int
) -> float:
    """Evaluate a single series element, short-circuiting conditional branches.

    Used only for formulas containing ``if``/``else``, comparisons, or boolean
    operators, so that the branch not selected for a given element (e.g. the
    numerator/denominator of a division-by-zero guard) is never evaluated for
    that element.
    """

    if isinstance(node, ast.Name):
        return environment[node.id][index]

    if isinstance(node, ast.Constant):
        assert isinstance(node.value, (int, float)) and not isinstance(node.value, bool)
        return float(node.value)

    if isinstance(node, ast.BinOp):
        left = _evaluate_node_at(node.left, environment, index)
        right = _evaluate_node_at(node.right, environment, index)
        return _BINARY_OPS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node_at(node.operand, environment, index)
        return _UNARY_OPS[type(node.op)](operand)

    if isinstance(node, ast.Compare):
        left = _evaluate_node_at(node.left, environment, index)
        result = True
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate_node_at(comparator, environment, index)
            if not _COMPARE_OPS[type(op)](left, right):
                result = False
                break
            left = right
        return 1.0 if result else 0.0

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = all(
                _evaluate_node_at(value, environment, index) for value in node.values
            )
        else:
            result = any(
                _evaluate_node_at(value, environment, index) for value in node.values
            )
        return 1.0 if result else 0.0

    if isinstance(node, ast.IfExp):
        test = _evaluate_node_at(node.test, environment, index)
        branch = node.body if test else node.orelse
        return _evaluate_node_at(branch, environment, index)

    if isinstance(node, ast.Call):
        return _evaluate_call_at(node, environment, index)

    msg = f"unsupported formula element: {type(node).__name__}"
    raise TypeError(msg)


def _evaluate_call(node: ast.Call, environment: dict[str, tuple[float, ...]]) -> Value:
    spec, window = _call_spec_and_window(node, environment)
    series = _evaluate_node(node.args[0], environment)
    if isinstance(series, float):
        return series
    return spec.apply(series, window)


def _evaluate_call_at(
    node: ast.Call, environment: dict[str, tuple[float, ...]], index: int
) -> float:
    spec, window = _call_spec_and_window_at(node, environment, index)
    start = max(0, index - window + 1)
    values = tuple(
        _evaluate_node_at(node.args[0], environment, neighbor)
        for neighbor in range(start, index + 1)
    )
    return spec.apply(values, window)[-1]


def _call_spec_and_window(
    node: ast.Call, environment: dict[str, tuple[float, ...]]
) -> tuple[FunctionSpec, int]:
    spec, window_node = _call_spec(node)
    window_value = _evaluate_node(window_node, environment)
    assert isinstance(window_value, float)
    return spec, int(window_value)


def _call_spec_and_window_at(
    node: ast.Call, environment: dict[str, tuple[float, ...]], index: int
) -> tuple[FunctionSpec, int]:
    spec, window_node = _call_spec(node)
    window_value = _evaluate_node_at(window_node, environment, index)
    return spec, int(window_value)


def _call_spec(node: ast.Call) -> tuple[FunctionSpec, ast.expr]:
    assert isinstance(node.func, ast.Name)
    spec = ALLOWED_FUNCTIONS[node.func.id]
    assert spec.window_arg is not None
    return spec, node.args[spec.window_arg]


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
