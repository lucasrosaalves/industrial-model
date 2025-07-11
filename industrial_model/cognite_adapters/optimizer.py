from threading import Lock

from cognite.client import CogniteClient

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
    def __init__(self, cognite_client: CogniteClient):
        self._all_spaces: list[str] | None = None
        self._cognite_client = cognite_client
        self._lock = Lock()

    def optimize(self, statement: Statement[TViewInstance]) -> None:
        instance_spaces = statement.entity.view_config.get("instance_spaces")
        instance_spaces_prefix = statement.entity.view_config.get(
            "instance_spaces_prefix"
        )

        if not instance_spaces and not instance_spaces_prefix:
            return

        if self._has_space_filter(statement.get_values().where_clauses):
            return

        filter_spaces = (
            self._find_spaces(instance_spaces_prefix) if instance_spaces_prefix else []
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

    def _find_spaces(self, instance_spaces_prefix: str) -> list[str]:
        all_spaces = self._load_spaces()

        return [
            space for space in all_spaces if space.startswith(instance_spaces_prefix)
        ]

    def _load_spaces(self) -> list[str]:
        all_spaces = self._all_spaces
        if all_spaces:
            return all_spaces

        with self._lock:
            if self._all_spaces:
                return self._all_spaces

            all_spaces = self._cognite_client.data_modeling.spaces.list(
                limit=-1
            ).as_ids()

            self._all_spaces = all_spaces
            return all_spaces
