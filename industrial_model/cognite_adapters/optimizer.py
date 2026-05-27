import asyncio

from cognite.client import AsyncCogniteClient

from industrial_model.models import TViewInstance
from industrial_model.statements import (
    BoolExpression,
    Expression,
    LeafExpression,
    Statement,
    col,
)

SPACE_PROPERTY = "space"


class QueryOptimizer:
    def __init__(self, cognite_client: AsyncCogniteClient):
        self._all_spaces: list[str] | None = None
        self._cognite_client = cognite_client
        self._lock = asyncio.Lock()

    async def optimize(self, statement: Statement[TViewInstance]) -> None:
        instance_spaces = statement.entity.view_config.get("instance_spaces")
        instance_spaces_prefix = statement.entity.view_config.get(
            "instance_spaces_prefix"
        )

        if not instance_spaces and not instance_spaces_prefix:
            return

        if self._has_space_filter(statement.get_values().where_clauses):
            return

        filter_spaces = (
            await self._find_spaces(instance_spaces_prefix)
            if instance_spaces_prefix
            else []
        )
        if instance_spaces:
            filter_spaces.extend(instance_spaces)

        if filter_spaces:
            statement.where(col(SPACE_PROPERTY).in_(filter_spaces))

    def _has_space_filter(self, where_clauses: list[Expression]) -> bool:
        for where_clause in where_clauses:
            if isinstance(where_clause, BoolExpression) and self._has_space_filter(
                where_clause.filters
            ):
                return True
            elif (
                isinstance(where_clause, LeafExpression)
                and where_clause.property == SPACE_PROPERTY
            ):
                return True

        return False

    async def _find_spaces(self, instance_spaces_prefix: str) -> list[str]:
        all_spaces = await self._load_spaces()
        return [
            space for space in all_spaces if space.startswith(instance_spaces_prefix)
        ]

    async def _load_spaces(self) -> list[str]:
        if self._all_spaces is not None:
            return self._all_spaces

        async with self._lock:
            if self._all_spaces is not None:
                return self._all_spaces

            result = await self._cognite_client.data_modeling.spaces.list(limit=-1)
            self._all_spaces = result.as_ids()
            return self._all_spaces
