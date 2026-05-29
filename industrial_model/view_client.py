from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar, cast

from industrial_model.engines import Engine
from industrial_model.models import (
    AggregatedViewInstance,
    PaginatedResult,
    WritableViewInstance,
)
from industrial_model.queries import (
    build_aggregation_statement,
    build_query_statement,
    build_search_statement,
)
from industrial_model.statements import AggregateTypes, SearchOperationTypes

_T = TypeVar("_T", bound=WritableViewInstance)
_TAgg = TypeVar("_TAgg", bound=AggregatedViewInstance)
_TFilter = TypeVar("_TFilter", bound=Mapping[str, Any])
_TQueryProperty = TypeVar("_TQueryProperty", bound=str)
_TGroupBy = TypeVar("_TGroupBy", bound=str)
_TAggregationProperty = TypeVar("_TAggregationProperty", bound=str)


class ViewClient(
    Generic[_T, _TAgg, _TFilter, _TQueryProperty, _TGroupBy, _TAggregationProperty]
):
    def __init__(
        self,
        engine: Engine,
        entity_cls: type[_T],
        aggregation_cls: type[_TAgg],
    ) -> None:
        self._engine = engine
        self._entity_cls = entity_cls
        self._aggregation_cls = aggregation_cls

    def aggregate(
        self,
        filters: _TFilter | None = None,
        *,
        aggregate_type: AggregateTypes | None = None,
        group_by_properties: list[_TGroupBy] | None = None,
        aggregation_property: _TAggregationProperty | None = None,
        limit: int | None = None,
    ) -> list[_TAgg]:
        return self._engine.aggregate(
            build_aggregation_statement(
                self._aggregation_cls,
                filters,
                aggregate_type=aggregate_type,
                group_by_properties=cast(list[str] | None, group_by_properties),
                aggregation_property=aggregation_property,
                limit=limit,
            )
        )

    async def aggregate_async(
        self,
        filters: _TFilter | None = None,
        *,
        aggregate_type: AggregateTypes | None = None,
        group_by_properties: list[_TGroupBy] | None = None,
        aggregation_property: _TAggregationProperty | None = None,
        limit: int | None = None,
    ) -> list[_TAgg]:
        return await self._engine.aggregate_async(
            build_aggregation_statement(
                self._aggregation_cls,
                filters,
                aggregate_type=aggregate_type,
                group_by_properties=cast(list[str] | None, group_by_properties),
                aggregation_property=aggregation_property,
                limit=limit,
            )
        )

    def search(
        self,
        filters: _TFilter | None = None,
        *,
        query: str | None = None,
        query_properties: list[_TQueryProperty] | None = None,
        query_operator: SearchOperationTypes | None = None,
        limit: int = 1000,
    ) -> list[_T]:
        return self._engine.search(
            build_search_statement(
                self._entity_cls,
                filters,
                query=query,
                query_properties=cast(list[str] | None, query_properties),
                query_operator=query_operator,
                limit=limit,
            )
        )

    async def search_async(
        self,
        filters: _TFilter | None = None,
        *,
        query: str | None = None,
        query_properties: list[_TQueryProperty] | None = None,
        query_operator: SearchOperationTypes | None = None,
        limit: int = 1000,
    ) -> list[_T]:
        return await self._engine.search_async(
            build_search_statement(
                self._entity_cls,
                filters,
                query=query,
                query_properties=cast(list[str] | None, query_properties),
                query_operator=query_operator,
                limit=limit,
            )
        )

    def query(
        self,
        filters: _TFilter | None = None,
        *,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> PaginatedResult[_T]:
        return self._engine.query(
            build_query_statement(
                self._entity_cls,
                filters,
                limit=limit,
                cursor=cursor,
            )
        )

    async def query_async(
        self,
        filters: _TFilter | None = None,
        *,
        limit: int = 1000,
        cursor: str | None = None,
    ) -> PaginatedResult[_T]:
        return await self._engine.query_async(
            build_query_statement(
                self._entity_cls,
                filters,
                limit=limit,
                cursor=cursor,
            )
        )

    def query_all_pages(
        self,
        filters: _TFilter | None = None,
        *,
        limit: int = 1000,
    ) -> list[_T]:
        return self._engine.query_all_pages(
            build_query_statement(self._entity_cls, filters, limit=limit)
        )

    async def query_all_pages_async(
        self,
        filters: _TFilter | None = None,
        *,
        limit: int = 1000,
    ) -> list[_T]:
        return await self._engine.query_all_pages_async(
            build_query_statement(self._entity_cls, filters, limit=limit)
        )

    def upsert(self, entries: list[_T], replace: bool = False) -> None:
        return self._engine.upsert(entries, replace)

    async def upsert_async(self, entries: list[_T], replace: bool = False) -> None:
        return await self._engine.upsert_async(entries, replace)

    def delete(self, nodes: list[_T]) -> None:
        return self._engine.delete(nodes)

    async def delete_async(self, nodes: list[_T]) -> None:
        return await self._engine.delete_async(nodes)
