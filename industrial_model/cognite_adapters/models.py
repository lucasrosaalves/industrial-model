from dataclasses import dataclass
from typing import Any

from cognite.client.data_classes.data_modeling import (
    EdgeApply,
    NodeApply,
)

from industrial_model.models.entities import EdgeContainer

_PAGE_SIZE = 1000


@dataclass
class UpsertOperation:
    nodes: list[NodeApply]
    edges: list[EdgeApply]
    edges_to_delete: list[EdgeContainer]

    def chunk_nodes(self) -> list[list[NodeApply]]:
        return self._chunk_list(self.nodes)

    def chunk_edges(self) -> list[list[EdgeApply]]:
        return self._chunk_list(self.edges)

    def chunk_edges_to_delete(self) -> list[list[EdgeContainer]]:
        return self._chunk_list(self.edges_to_delete)

    def _chunk_list(self, entries: list[Any]) -> list[list[Any]]:
        data: list[list[Any]] = []
        for i in range(0, len(entries), _PAGE_SIZE):
            start = i
            end = i + _PAGE_SIZE
            data.append(entries[start:end])
        return data
