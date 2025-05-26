from cognite.client import CogniteClient

from industrial_model.config import DataModelId
from industrial_model.models import (
    PaginatedResult,
    TAggregatedViewInstance,
    TViewInstance,
    TWritableViewInstance,
    ValidationMode,
)
from industrial_model.statements import AggregationStatement, Statement
from industrial_model.utils import run_async

from .engine import Engine


class AsyncEngine:
    def __init__(
        self,
        cognite_client: CogniteClient,
        data_model_id: DataModelId,
    ):
        self._engine = Engine(cognite_client, data_model_id)

    async def query_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> PaginatedResult[TViewInstance]:
        return await run_async(self._engine.query, statement, validation_mode)

    async def query_all_pages_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        return await run_async(
            self._engine.query_all_pages, statement, validation_mode
        )

    async def aggregate_async(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[TAggregatedViewInstance]:
        return await run_async(self._engine.aggregate, statement)

    async def upsert_async(
        self, entries: list[TWritableViewInstance], replace: bool = False
    ) -> None:
        return await run_async(self._engine.upsert, entries, replace)
