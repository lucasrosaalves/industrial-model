from dataclasses import dataclass

import cognite.client.data_classes.filters as filters
from cognite.client.data_classes.aggregations import Count, MetricAggregation
from cognite.client.data_classes.data_modeling import (
    View,
)

from industrial_model.models import TViewInstance
from industrial_model.statements import AggregationStatement

from .filter_mapper import (
    FilterMapper,
)
from .view_mapper import ViewMapper


@dataclass
class AggregationQuery:
    view: View
    metric_aggregation: MetricAggregation
    filters: filters.Filter | None
    group_by_columns: list[str]
    limit: int


class AggregationMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper
        self._filter_mapper = FilterMapper(view_mapper)

    def map(
        self, statement: AggregationStatement[TViewInstance]
    ) -> AggregationQuery:
        root_node = statement.entity.get_view_external_id()

        root_view = self._view_mapper.get_view(root_node)

        filters_ = (
            filters.And(
                *self._filter_mapper.map(statement.where_clauses, root_view)
            )
            if statement.where_clauses
            else None
        )

        metric_aggregation = (
            Count(statement.aggregation_property.property)
            if statement.aggregate_ == "count"
            else None
        )
        if metric_aggregation is None:
            raise ValueError(
                f"Unsupported aggregate function: {statement.aggregate_}"
            )
        return AggregationQuery(
            view=root_view,
            metric_aggregation=metric_aggregation,
            filters=filters_,
            group_by_columns=[
                column.property for column in statement.group_by_columns
            ],
            limit=statement.limit_,
        )
