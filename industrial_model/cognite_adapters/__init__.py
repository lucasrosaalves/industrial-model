import logging
from typing import Any

from cognite.client import CogniteClient
from cognite.client.data_classes.data_modeling import Edge, Node
from cognite.client.data_classes.data_modeling.query import (
    Query as CogniteQuery,
)
from cognite.client.data_classes.data_modeling.query import (
    QueryResult as CogniteQueryResult,
)

from industrial_model.config import DataModelId
from industrial_model.models import (
    TAggregatedViewInstance,
    TViewInstance,
    TWritableViewInstance,
)
from industrial_model.statements import AggregationStatement, Statement

from .aggregation_mapper import AggregationMapper
from .optimizer import QueryOptimizer
from .query_mapper import QueryMapper
from .query_result_mapper import (
    QueryResultMapper,
)
from .upsert_mapper import UpsertMapper
from .utils import (
    append_nodes_and_edges,
    get_query_for_dependencies_pagination,
    map_nodes_and_edges,
)
from .view_mapper import ViewMapper


class CogniteAdapter:
    def __init__(
        self, cognite_client: CogniteClient, data_model_id: DataModelId
    ):
        self._cognite_client = cognite_client

        view_mapper = ViewMapper(cognite_client, data_model_id)
        self._optmizer = QueryOptimizer(cognite_client, data_model_id)
        self._query_mapper = QueryMapper(view_mapper)
        self._result_mapper = QueryResultMapper(view_mapper)
        self._upsert_mapper = UpsertMapper(view_mapper)
        self._aggregation_mapper = AggregationMapper(view_mapper)

    def query(
        self, statement: Statement[TViewInstance], all_pages: bool
    ) -> tuple[list[dict[str, Any]], str | None]:
        self._optmizer.optimize(statement)
        cognite_query = self._query_mapper.map(statement)
        view_external_id = statement.entity.get_view_external_id()

        data: list[dict[str, Any]] = []
        while True:
            query_result = self._cognite_client.data_modeling.instances.query(
                cognite_query
            )

            dependencies_data = self._query_dependencies_pages(
                cognite_query, query_result, view_external_id
            )

            query_result_data = append_nodes_and_edges(
                map_nodes_and_edges(query_result, cognite_query),
                dependencies_data,
            )

            page_result = self._result_mapper.map_nodes(
                view_external_id,
                query_result_data,
            )
            next_cursor = query_result.cursors.get(view_external_id)
            data.extend(page_result)

            last_page = len(page_result) < statement.limit_ or not next_cursor
            next_cursor_ = None if last_page else next_cursor
            cognite_query.cursors = {view_external_id: next_cursor_}

            if not all_pages or last_page:
                return data, next_cursor_

    def aggregate(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[dict[str, Any]]:
        query = self._aggregation_mapper.map(statement)

        result = self._cognite_client.data_modeling.instances.aggregate(
            view=query.view.as_id(),
            aggregates=query.metric_aggregation,
            filter=query.filters,
            group_by=query.group_by_columns,
            limit=query.limit,
        )
        data: list[dict[str, Any]] = []
        for item in result:
            if not item.aggregates or item.aggregates[0].value is None:
                continue

            entry = item.group if item.group else {}
            entry["value"] = item.aggregates[0].value
            data.append(entry)
        return data

    def upsert(
        self, entries: list[TWritableViewInstance], replace: bool = False
    ) -> None:
        logger = logging.getLogger(__name__)
        operation = self._upsert_mapper.map(entries)

        for node_chunk in operation.chunk_nodes():
            logger.info(
                f"Upserting {len(node_chunk)} nodes (replace={replace})"
            )
            self._cognite_client.data_modeling.instances.apply(
                nodes=node_chunk,
                replace=replace,
            )

        for edge_chunk in operation.chunk_edges():
            logger.info(
                f"Upserting {len(edge_chunk)} edges (replace={replace})"
            )
            self._cognite_client.data_modeling.instances.apply(
                edges=edge_chunk,
                replace=replace,
            )

        for edges_to_remove_chunk in operation.chunk_edges_to_delete():
            logger.info(f"Deleting {len(edges_to_remove_chunk)} edges")
            self._cognite_client.data_modeling.instances.delete(
                edges=[item.as_tuple() for item in edges_to_remove_chunk],
            )

    def _query_dependencies_pages(
        self,
        cognite_query: CogniteQuery,
        query_result: CogniteQueryResult,
        view_external_id: str,
    ) -> dict[str, list[Node | Edge]] | None:
        new_query = get_query_for_dependencies_pagination(
            cognite_query, query_result, view_external_id
        )
        if not new_query:
            return None

        new_query_result = self._cognite_client.data_modeling.instances.query(
            new_query
        )

        result = map_nodes_and_edges(new_query_result, new_query)

        nested_results = self._query_dependencies_pages(
            new_query, new_query_result, view_external_id
        )
        return append_nodes_and_edges(result, nested_results)
