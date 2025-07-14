import datetime
from abc import ABC
from dataclasses import dataclass
from typing import Any

from industrial_model.constants import (
    BOOL_EXPRESSION_OPERATORS,
    LEAF_EXPRESSION_OPERATORS,
)

RANGE_SUPPORTED_VALUES = str | int | float
LIST_SUPPORTED_VALUES = list[str] | list[int] | list[float] | list[dict[str, str]]
SUPPORTED_VALUES = (
    RANGE_SUPPORTED_VALUES | bool | dict[str, str] | LIST_SUPPORTED_VALUES
)


class Expression(ABC):
    operator: str


@dataclass(frozen=True)
class BoolExpression(Expression):
    filters: list[Expression]
    operator: BOOL_EXPRESSION_OPERATORS

    def __and__(self, other: "BoolExpression | LeafExpression") -> bool:
        return and_(self, other)

    def __or__(self, other: "BoolExpression | LeafExpression") -> bool:
        return or_(self, other)


@dataclass(frozen=True)
class LeafExpression(Expression):
    property: str
    operator: LEAF_EXPRESSION_OPERATORS
    value: Any

    def __and__(self, other: "BoolExpression | LeafExpression") -> bool:
        return and_(self, other)

    def __or__(self, other: "BoolExpression | LeafExpression") -> bool:
        return or_(self, other)


class Column:
    def __init__(self, property: Any):
        assert isinstance(property, str | Column)
        property_ = property.property if isinstance(property, Column) else property
        self.property: str = property_

    def __hash__(self) -> int:
        return hash(self.property)

    def __eq__(self, other: Any) -> bool:
        if other is None:
            return self.not_exists_()

        return self.equals_(other)

    def __ne__(self, other: Any) -> bool:
        if other is None:
            return self.exists_()

        return self.not_("==", other)

    def __lt__(self, other: Any) -> bool:
        return self.lt_(other)

    def __le__(self, other: Any) -> bool:
        return self.lte_(other)

    def __gt__(self, other: Any) -> bool:
        return self.gt_(other)

    def __ge__(self, other: Any) -> bool:
        return self.gte_(other)

    def equals_(self, other: SUPPORTED_VALUES) -> bool:
        return self._compare("==", other)

    def prefix(self, other: str) -> bool:
        return self._compare("prefix", other)

    def lt_(self, other: RANGE_SUPPORTED_VALUES | datetime.datetime) -> bool:
        return self._compare("<", other)

    def lte_(self, other: RANGE_SUPPORTED_VALUES | datetime.datetime) -> bool:
        return self._compare("<=", other)

    def gt_(self, other: RANGE_SUPPORTED_VALUES | datetime.datetime) -> bool:
        return self._compare(">", other)

    def gte_(self, other: RANGE_SUPPORTED_VALUES | datetime.datetime) -> bool:
        return self._compare(">=", other)

    def in_(self, other: LIST_SUPPORTED_VALUES) -> bool:
        return self._compare("in", other)

    def contains_all_(self, other: LIST_SUPPORTED_VALUES) -> bool:
        return self._compare("containsAll", other)

    def contains_any_(self, other: LIST_SUPPORTED_VALUES) -> bool:
        return self._compare("containsAny", other)

    def exists_(self) -> bool:
        return self._compare("exists", None)

    def not_exists_(self) -> bool:
        return self.not_("exists", None)

    def not_(self, operator: LEAF_EXPRESSION_OPERATORS, other: Any) -> bool:
        return BoolExpression(
            operator="not",
            filters=[self._compare(operator, other)],  # type: ignore
        )

    def nested_(self, expression: bool | LeafExpression | BoolExpression) -> bool:
        if not isinstance(expression, Expression):
            raise ValueError("Invalid expression")

        return self._compare("nested", expression)

    def _compare(self, operator: LEAF_EXPRESSION_OPERATORS, value: Any) -> bool:
        if isinstance(value, Column):
            raise ValueError("can not compare two columns in a graphdb")

        return LeafExpression(property=self.property, operator=operator, value=value)  # type: ignore


def _unwrap_expressions(
    *expressions: bool | LeafExpression | BoolExpression,
) -> list[Expression]:
    filters: list[Expression] = []
    for expression in expressions:
        assert isinstance(expression, Expression)
        filters.append(expression)
    return filters


def and_(*expressions: bool | LeafExpression | BoolExpression) -> bool:
    return BoolExpression(operator="and", filters=_unwrap_expressions(*expressions))  # type: ignore


def or_(*expressions: bool | LeafExpression | BoolExpression) -> bool:
    return BoolExpression(operator="or", filters=_unwrap_expressions(*expressions))  # type: ignore


def not_(*expressions: bool | LeafExpression | BoolExpression) -> bool:
    return BoolExpression(operator="not", filters=_unwrap_expressions(*expressions))  # type: ignore


def col(property: Any) -> Column:
    return Column(property)
