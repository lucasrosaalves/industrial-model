from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from industrial_model.constants import (
    BOOL_EXPRESSION_OPERATORS,
    LEAF_EXPRESSION_OPERATORS,
)
from industrial_model.statements import BoolExpression, Expression, LeafExpression

# Python filter key → CDF operator
_OPERATOR_MAP: dict[str, LEAF_EXPRESSION_OPERATORS] = {
    "eq": "==",
    "in": "in",
    "in_": "in",
    "prefix": "prefix",
    "exists": "exists",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "containsAny": "containsAny",
    "containsAll": "containsAll",
}


def parse_filters(
    filters: Mapping[str, Any],
) -> list[Expression]:
    expressions: list[Expression] = []

    for key, value in filters.items():
        if value is None:
            continue

        if key in ("OR", "AND"):
            bool_op: BOOL_EXPRESSION_OPERATORS = "or" if key == "OR" else "and"
            branches = value if isinstance(value, list) else [value]
            branch_exprs = []
            for branch in branches:
                if not isinstance(branch, Mapping):
                    continue
                sub = parse_filters(branch)
                if sub:
                    branch_exprs.append(_to_single_expression(sub))
            if branch_exprs:
                expressions.append(
                    BoolExpression(operator=bool_op, filters=branch_exprs)
                )
            continue

        if key == "NOT":
            branches = value if isinstance(value, list) else [value]
            branch_exprs = []
            for branch in branches:
                if not isinstance(branch, Mapping):
                    continue
                sub = parse_filters(branch)
                if sub:
                    branch_exprs.append(_to_single_expression(sub))
            if branch_exprs:
                expressions.append(
                    BoolExpression(
                        operator="not",
                        filters=[_to_single_expression(branch_exprs)],
                    )
                )
            continue

        if not isinstance(value, Mapping):
            continue

        property_ = _to_property_name(key)
        if _is_leaf_filter(value):
            for op_name, op_value in value.items():
                cdf_op = _OPERATOR_MAP.get(op_name)
                if cdf_op is None:
                    continue
                expressions.append(_make_leaf_expression(property_, cdf_op, op_value))
            continue

        sub = parse_filters(value)
        if sub:
            expressions.append(
                LeafExpression(
                    property=property_,
                    operator="nested",
                    value=_to_single_expression(sub),
                )
            )

    return expressions


def _is_leaf_filter(value: Mapping[str, Any]) -> bool:
    return any(key in _OPERATOR_MAP for key in value)


def _to_property_name(key: str) -> str:
    key = key.removesuffix("_")
    if "_" not in key:
        return key

    first, *rest = key.split("_")
    return first + "".join(part[:1].upper() + part[1:] for part in rest if part)


def _to_single_expression(expressions: list[Expression]) -> Expression:
    if len(expressions) == 1:
        return expressions[0]
    return BoolExpression(operator="and", filters=expressions)


def _make_leaf_expression(
    property_: str,
    cdf_op: LEAF_EXPRESSION_OPERATORS,
    value: Any,
) -> Expression:
    if cdf_op == "exists" and isinstance(value, bool) and not value:
        return BoolExpression(
            operator="not",
            filters=[LeafExpression(property=property_, operator="exists", value=True)],
        )

    return LeafExpression(property=property_, operator=cdf_op, value=value)
