from dataclasses import dataclass

import cognite.client.data_classes.filters as filters
from cognite.client.data_classes.data_modeling import InstanceSort, View

from industrial_model.models import TViewInstance
from industrial_model.statements import SearchStatement

from .filter_mapper import (
    FilterMapper,
)
from .sort_mapper import SortMapper
from .view_mapper import ViewMapper


@dataclass
class SearchQuery:
    view: View
    filter: filters.Filter | None
    query: str | None
    query_properties: list[str] | None
    limit: int
    sort: list[InstanceSort]


class SearchMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper
        self._filter_mapper = FilterMapper(view_mapper)
        self._sort_mapper = SortMapper()

    def map(self, statement: SearchStatement[TViewInstance]) -> SearchQuery:
        root_node = statement.entity.get_view_external_id()

        root_view = self._view_mapper.get_view(root_node)

        filters_ = self._filter_mapper.map(statement.where_clauses, root_view)

        sort_clauses = self._sort_mapper.map(statement.sort_clauses, root_view)
        for item in sort_clauses:
            item.nulls_first = None

        return SearchQuery(
            view=root_view,
            filter=filters.And(*filters_) if filters_ else None,
            query=statement.query,
            query_properties=statement.query_properties,
            limit=statement.limit_,
            sort=sort_clauses,
        )
