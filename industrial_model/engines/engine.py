from typing import Any

from cognite.client import CogniteClient

from industrial_model.cognite_adapters import CogniteAdapter
from industrial_model.config import DataModelId
from industrial_model.models import (
    EdgeContainer,
    PaginatedResult,
    TAggregatedViewInstance,
    TViewInstance,
    TWritableViewInstance,
    ValidationMode,
)
from industrial_model.statements import AggregationStatement, Statement


class Engine:
    def __init__(
        self,
        cognite_client: CogniteClient,
        data_model_id: DataModelId,
    ):
        self._cognite_adapter = CogniteAdapter(cognite_client, data_model_id)

    def query(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> PaginatedResult[TViewInstance]:
        data, next_cursor = self._cognite_adapter.query(statement, False)

        return PaginatedResult(
            data=self._validate_data(statement.entity, data, validation_mode),
            next_cursor=next_cursor,
            has_next_page=next_cursor is not None,
        )

    def query_all_pages(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        if statement.cursor_:
            raise ValueError("Cursor should be none when querying all pages")

        data, _ = self._cognite_adapter.query(statement, True)

        return self._validate_data(statement.entity, data, validation_mode)

    def aggregate(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[TAggregatedViewInstance]:
        data = self._cognite_adapter.aggregate(statement)

        return [statement.entity.model_validate(item) for item in data]

    def upsert(
        self, entries: list[TWritableViewInstance], replace: bool = False
    ) -> None:
        if not entries:
            return

        return self._cognite_adapter.upsert(entries, replace)

    def _validate_data(
        self,
        entity: type[TViewInstance],
        data: list[dict[str, Any]],
        validation_mode: ValidationMode,
    ) -> list[TViewInstance]:
        result: list[TViewInstance] = []
        for item in data:
            try:
                validated_item = entity.model_validate(item)
                self._include_edges(item, validated_item)
                result.append(validated_item)
            except Exception:
                if validation_mode == "ignoreOnError":
                    continue
                raise
        return result

    def _include_edges(
        self, item: dict[str, Any], validated_item: TViewInstance
    ) -> None:
        if "_edges" not in item or not isinstance(item["_edges"], dict):
            return
        entries: dict[str, list[EdgeContainer]] = {}
        for property_, edges in item["_edges"].items():
            if not edges or not isinstance(edges, list):
                continue

            assert isinstance(edges[0], EdgeContainer)
            entries[property_] = edges
        validated_item._edges = entries
