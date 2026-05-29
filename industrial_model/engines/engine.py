import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from cognite.client import CogniteClient

from industrial_model.cognite_adapters import CogniteAdapter
from industrial_model.config import DataModelId
from industrial_model.models import (
    PaginatedResult,
    TAggregatedViewInstance,
    TViewInstance,
    TWritableViewInstance,
    ValidationMode,
    include_edges,
)
from industrial_model.statements import (
    AggregationStatement,
    SearchStatement,
    Statement,
)

from ._internal import (
    UserToken,
    generate_engine_params,
    generate_engine_params_from_user_token,
)

_T = TypeVar("_T")


class Engine:
    def __init__(
        self,
        cognite_client: CogniteClient,
        data_model_id: DataModelId,
    ):
        self._cognite_adapter = CogniteAdapter(
            cognite_client.get_async_client(), data_model_id
        )

    async def search_async(
        self,
        statement: SearchStatement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        data = await self._cognite_adapter.search(statement)
        return self._validate_data(statement.entity, data, validation_mode)

    async def query_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> PaginatedResult[TViewInstance]:
        data, next_cursor = await self._cognite_adapter.query(statement, False)
        return PaginatedResult(
            data=self._validate_data(statement.entity, data, validation_mode),
            next_cursor=next_cursor,
            has_next_page=next_cursor is not None,
        )

    async def query_all_pages_async(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        if statement.get_values().cursor:
            raise ValueError("Cursor should be none when querying all pages")
        data, _ = await self._cognite_adapter.query(statement, True)
        return self._validate_data(statement.entity, data, validation_mode)

    async def aggregate_async(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[TAggregatedViewInstance]:
        data = await self._cognite_adapter.aggregate(statement)
        return [statement.entity.model_validate(item) for item in data]

    async def upsert_async(
        self,
        entries: list[TWritableViewInstance],
        replace: bool = False,
        remove_unset: bool = False,
    ) -> None:
        if not entries:
            return
        await self._cognite_adapter.upsert(entries, replace, remove_unset)

    async def delete_async(self, nodes: list[TViewInstance]) -> None:
        await self._cognite_adapter.delete(nodes)

    @staticmethod
    def _run_sync(coro: Coroutine[Any, Any, _T]) -> _T:
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "Engine sync methods cannot be called from an async context. "
                "Use the async variants instead (e.g. query_async, search_async)."
            )
        except RuntimeError as exc:
            if "async context" in str(exc):
                raise
        return asyncio.run(coro)

    def search(
        self,
        statement: SearchStatement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        return self._run_sync(self.search_async(statement, validation_mode))

    def query(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> PaginatedResult[TViewInstance]:
        return self._run_sync(self.query_async(statement, validation_mode))

    def query_all_pages(
        self,
        statement: Statement[TViewInstance],
        validation_mode: ValidationMode = "raiseOnError",
    ) -> list[TViewInstance]:
        return self._run_sync(self.query_all_pages_async(statement, validation_mode))

    def aggregate(
        self, statement: AggregationStatement[TAggregatedViewInstance]
    ) -> list[TAggregatedViewInstance]:
        return self._run_sync(self.aggregate_async(statement))

    def upsert(
        self,
        entries: list[TWritableViewInstance],
        replace: bool = False,
        remove_unset: bool = False,
    ) -> None:
        self._run_sync(self.upsert_async(entries, replace, remove_unset))

    def delete(self, nodes: list[TViewInstance]) -> None:
        self._run_sync(self.delete_async(nodes))

    @classmethod
    def from_config_file(cls, config_file: str | Path) -> "Engine":
        client, dm_id = generate_engine_params(config_file)
        return cls(client, dm_id)

    @classmethod
    def from_user_token(
        cls,
        *,
        user_token: UserToken,
        project: str,
        data_model_id: DataModelId | dict[str, str],
        client_name: str = "industrial-model",
        base_url: str | None = None,
        cluster: str | None = None,
    ) -> "Engine":
        client, dm_id = generate_engine_params_from_user_token(
            user_token=user_token,
            project=project,
            data_model_id=data_model_id,
            client_name=client_name,
            base_url=base_url,
            cluster=cluster,
        )
        return cls(client, dm_id)

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
                include_edges(item, validated_item)
                result.append(validated_item)
            except Exception:
                if validation_mode == "ignoreOnError":
                    continue
                raise
        return result
