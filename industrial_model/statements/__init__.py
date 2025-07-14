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
class BaseStatementValues:
    where_clauses: list[Expression] = field(init=False, default_factory=list)
    where_edge_clauses: list[tuple[Column, list[Expression]]] = field(
        init=False, default_factory=list
    )
    sort_clauses: list[tuple[Column, SORT_DIRECTION]] = field(
        init=False, default_factory=list
    )
    limit: int = field(init=False, default=DEFAULT_LIMIT)
    cursor: str | None = field(init=False, default=None)

    query: str | None = field(init=False, default=None)
    query_properties: list[str] | None = field(init=False, default=None)


@dataclass
class BaseStatement(Generic[T]):
    entity: type[T] = field(init=True)
    _values: BaseStatementValues = field(
        init=False, default_factory=lambda: BaseStatementValues()
    )

    def where(self, *expressions: bool | Expression) -> Self:
        for expression in expressions:
            assert isinstance(expression, Expression)
            self._values.where_clauses.append(expression)
        return self

    def limit(self, limit: int) -> Self:
        self._values.limit = limit
        return self

    def asc(self, property: str | Column | Any) -> Self:
        return self.sort(property, "ascending")

    def desc(self, property: str | Column | Any) -> Self:
        return self.sort(property, "descending")

    def sort(self, property: str | Column | Any, direction: SORT_DIRECTION) -> Self:
        self._values.sort_clauses.append(
            (
                _create_column(property),
                direction,
            )
        )
        return self

    def get_values(self) -> BaseStatementValues:
        return self._values


@dataclass
class Statement(BaseStatement[T]):
    def cursor(self, cursor: str | None) -> Self:
        self._values.cursor = cursor
        return self

    def where_edge(
        self, property: str | Column | Any, *expressions: bool | Expression
    ) -> Self:
        if not expressions:
            return self

        expressions_: list[Expression] = []
        for expression in expressions:
            assert isinstance(expression, Expression)
            expressions_.append(expression)

        self._values.where_edge_clauses.append(
            (
                _create_column(property),
                expressions_,
            )
        )
        return self


@dataclass
class SearchStatement(BaseStatement[T]):
    def query_by(
        self,
        query: str,
        query_properties: list[Column] | list[str] | list[Any] | None = None,
    ) -> Self:
        self._values.query = query
        self._values.query_properties = (
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
class AggregationStatementValues:
    group_by_properties: list[Column] | None = field(init=False, default=None)
    aggregation_property: Column = field(init=False, default=Column("externalId"))
    where_clauses: list[Expression] = field(init=False, default_factory=list)
    limit: int = field(init=False, default=-1)


@dataclass
class AggregationStatement(Generic[T]):
    entity: type[T] = field(init=True)
    aggregate: AggregateTypes = field(init=True)

    _values: AggregationStatementValues = field(
        init=False, default_factory=lambda: AggregationStatementValues()
    )

    def group_by(self, *property: str | Column | Any) -> Self:
        self._values.group_by_properties = [_create_column(prop) for prop in property]
        return self

    def aggregate_by(self, property: str | Column | Any) -> Self:
        self._values.aggregation_property = _create_column(property)
        return self

    def where(self, *expressions: bool | Expression) -> Self:
        for expression in expressions:
            assert isinstance(expression, Expression)
            self._values.where_clauses.append(expression)
        return self

    def limit(self, limit: int) -> Self:
        self._values.limit = limit
        return self

    def get_values(self) -> AggregationStatementValues:
        return self._values


def select(entity: type[T]) -> Statement[T]:
    return Statement(entity)


def aggregate(
    entity: type[T],
    aggregate: AggregateTypes | None = "count",
) -> AggregationStatement[T]:
    return AggregationStatement(entity=entity, aggregate=aggregate or "count")


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
