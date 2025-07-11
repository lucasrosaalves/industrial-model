from pathlib import Path

from cognite.client import CogniteClient

from industrial_model.config import DataModelId
from industrial_model.models import (
    PaginatedResult,
    TAggregatedViewInstance,
    TViewInstance,
    TWritableViewInstance,
    ValidationMode,
)
from industrial_model.statements import (
    AggregationStatement,
    SearchStatement,
    Statement,
)

from ._internal import generate_engine_params
from .engine import Engine


class AsyncEngine:
    def __init__(
        self,
        cognite_client: CogniteClient,
        data_model_id: DataModelId,
    ):
        self._engine = Engine(cognite_client, data_model_id)

    async def search_async(
        self,
        statement: SearchStatement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        return await self._engine.search_async(statement, validation_mode)

    async def query_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> PaginatedResult[TViewInstance]:
        return await self._engine.query_async(statement, validation_mode)

    async def query_all_pages_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        return await self._engine.query_all_pages_async(statement, validation_mode)

    async def aggregate_async(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[TAggregatedViewInstance]:
        return await self._engine.aggregate_async(statement)

    async def upsert_async(
        self, entries: list[TWritableViewInstance], replace: bool = False
    ) -> None:
        return await self._engine.upsert_async(entries, replace)

    async def delete_async(self, nodes: list[TViewInstance]) -> None:
        return await self._engine.delete_async(nodes)

    @classmethod
    def from_config_file(cls, config_file: str | Path) -> "AsyncEngine":
        client, dm_id = generate_engine_params(config_file)
        return AsyncEngine(client, dm_id)
