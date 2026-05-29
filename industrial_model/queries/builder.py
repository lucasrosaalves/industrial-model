from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from industrial_model.models import TAggregatedViewInstance, TViewInstance
from industrial_model.statements import (
    AggregateTypes,
    AggregationStatement,
    SearchOperationTypes,
    SearchStatement,
    Statement,
    aggregate,
    search,
    select,
)

from .parser import parse_filters


def build_query_statement(
    entity_cls: type[TViewInstance],
    filters: Mapping[str, Any] | None = None,
    *,
    exclude_relations: list[str] | None = None,
    limit: int = 1000,
    cursor: str | None = None,
) -> Statement[TViewInstance]:
    statement = select(entity_cls)
    if filters:
        statement.where(*parse_filters(filters))
    if exclude_relations:
        for relation_property in exclude_relations:
            statement.relation_mode(relation_property, "instanceId")
    statement.limit(limit)
    statement.cursor(cursor)
    return statement


def build_search_statement(
    entity_cls: type[TViewInstance],
    filters: Mapping[str, Any] | None = None,
    *,
    query: str | None = None,
    query_properties: list[str] | None = None,
    query_operator: SearchOperationTypes | None = None,
    limit: int = 1000,
) -> SearchStatement[TViewInstance]:
    statement = search(entity_cls)
    if filters:
        statement.where(*parse_filters(filters))
    if query:
        statement.query_by(query, query_properties, query_operator)
    statement.limit(limit)
    return statement


def build_aggregation_statement(
    aggregation_cls: type[TAggregatedViewInstance],
    filters: Mapping[str, Any] | None = None,
    *,
    aggregate_type: AggregateTypes | None = None,
    group_by_properties: list[str] | None = None,
    aggregation_property: str | None = None,
    limit: int | None = None,
) -> AggregationStatement[TAggregatedViewInstance]:
    statement = aggregate(aggregation_cls, aggregate_type)
    if filters:
        statement.where(*parse_filters(filters))
    if group_by_properties:
        statement.group_by(*group_by_properties)
    if aggregation_property:
        statement.aggregate_by(aggregation_property)
    if limit:
        statement.limit(limit)
    return statement
