from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Self, TypeVar

from industrial_model.constants import DEFAULT_LIMIT, SORT_DIRECTION

from .expressions import (
    BoolExpression,
    Column,
    Expression,
    LeafExpression,
    and_,
    col,
    not_,
    or_,
)

T = TypeVar("T")
AggregateTypes = Literal["count", "avg", "min", "max", "sum"]


def _create_column(property: str | Column | Any) -> Column:
    return property if isinstance(property, Column) else Column(property)


@dataclass
class BaseStatement(Generic[T]):
    entity: type[T] = field(init=True)
    where_clauses: list[Expression] = field(init=False, default_factory=list)
    sort_clauses: list[tuple[Column, SORT_DIRECTION]] = field(
        init=False, default_factory=list
    )
    limit_: int = field(init=False, default=DEFAULT_LIMIT)

    def where(self, *expressions: bool | Expression) -> Self:
        for expression in expressions:
            assert isinstance(expression, Expression)
            self.where_clauses.append(expression)
        return self

    def limit(self, limit: int) -> Self:
        self.limit_ = limit
        return self

    def asc(self, property: str | Column | Any) -> Self:
        return self.sort(property, "ascending")

    def desc(self, property: str | Column | Any) -> Self:
        return self.sort(property, "descending")

    def sort(self, property: str | Column | Any, direction: SORT_DIRECTION) -> Self:
        self.sort_clauses.append(
            (
                _create_column(property),
                direction,
            )
        )
        return self


@dataclass
class Statement(BaseStatement[T]):
    cursor_: str | None = field(init=False, default=None)

    def cursor(self, cursor: str | None) -> Self:
        self.cursor_ = cursor
        return self


@dataclass
class SearchStatement(BaseStatement[T]):
    query: str | None = field(init=False, default=None)
    query_properties: list[str] | None = field(init=False, default=None)

    def query_by(
        self,
        query: str,
        query_properties: list[Column | str | Any] | None = None,
    ) -> Self:
        self.query = query
        self.query_properties = (
            [
                prop
                if isinstance(prop, str)
                else prop.property
                if isinstance(prop, Column)
                else str(prop)
                for prop in query_properties
            ]
            if query_properties
            else None
        )
        return self


@dataclass
class AggregationStatement(Generic[T]):
    entity: type[T] = field(init=True)
    aggregate: AggregateTypes = field(init=True)

    aggregation_property: Column = field(init=False, default=Column("externalId"))
    where_clauses: list[Expression] = field(init=False, default_factory=list)
    limit_: int = field(init=False, default=-1)

    def aggregate_by(self, property: str | Column | Any) -> Self:
        self.aggregation_property = _create_column(property)
        return self

    def where(self, *expressions: bool | Expression) -> Self:
        for expression in expressions:
            assert isinstance(expression, Expression)
            self.where_clauses.append(expression)
        return self

    def limit(self, limit: int) -> Self:
        self.limit_ = limit
        return self


def select(entity: type[T]) -> Statement[T]:
    return Statement(entity)


def aggregate(
    entity: type[T],
    aggregate: AggregateTypes = "count",
) -> AggregationStatement[T]:
    return AggregationStatement(entity=entity, aggregate=aggregate)


def search(entity: type[T]) -> SearchStatement[T]:
    return SearchStatement(entity)


__all__ = [
    "aggregate",
    "AggregationStatement",
    "Statement",
    "select",
    "search",
    "SearchStatement",
    "Column",
    "col",
    "Expression",
    "LeafExpression",
    "BoolExpression",
    "and_",
    "not_",
    "or_",
]
