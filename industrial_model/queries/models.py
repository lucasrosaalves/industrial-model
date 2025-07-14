from typing import Any

from industrial_model.models import RootModel, TAggregatedViewInstance, TViewInstance
from industrial_model.statements import (
    AggregateTypes,
    AggregationStatement,
    SearchStatement,
    Statement,
    aggregate,
    search,
    select,
)

from .utils import extract_base_statement_params


class BaseQuery(RootModel):
    def to_statement(self, entity: type[TViewInstance]) -> Statement[TViewInstance]:
        statement = select(entity)
        _set_base_statement_params(self, statement)

        return statement


class BasePaginatedQuery(BaseQuery):
    limit: int = 1000
    cursor: str | None = None

    def to_statement(self, entity: type[TViewInstance]) -> Statement[TViewInstance]:
        statement = super().to_statement(entity)
        statement.limit(self.limit)
        statement.cursor(self.cursor)

        return statement


class BaseSearchQuery(RootModel):
    query: str | None = None
    query_properties: list[Any] | None = None
    limit: int = 1000

    def to_statement(
        self, entity: type[TViewInstance]
    ) -> SearchStatement[TViewInstance]:
        statement = search(entity)
        _set_base_statement_params(self, statement)
        if self.query:
            statement.query_by(self.query, self.query_properties)
        statement.limit(self.limit)

        return statement


class BaseAggregationQuery(RootModel):
    aggregate: AggregateTypes | None = None
    group_by_properties: list[Any] | None = None
    aggregation_property: str | None = None
    limit: int | None = None

    def to_statement(
        self, entity: type[TAggregatedViewInstance]
    ) -> AggregationStatement[TAggregatedViewInstance]:
        statement = aggregate(entity, self.aggregate)

        _set_base_statement_params(self, statement)

        if self.group_by_properties:
            statement.group_by(*self.group_by_properties)

        if self.aggregation_property:
            statement.aggregate_by(self.aggregation_property)

        if self.limit:
            statement.limit(self.limit)

        return statement


def _set_base_statement_params(
    entity: RootModel,
    statement: Statement[TViewInstance]
    | SearchStatement[TViewInstance]
    | AggregationStatement[TAggregatedViewInstance],
) -> None:
    filters_, sort_params = extract_base_statement_params(entity)
    statement.where(*filters_)

    if isinstance(statement, AggregationStatement):
        return

    for sort_value, direction in sort_params:
        statement.sort(sort_value, direction)
