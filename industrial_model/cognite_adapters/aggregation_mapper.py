from dataclasses import dataclass

import cognite.client.data_classes.filters as filters
from cognite.client.data_classes.aggregations import (
    Avg,
    Count,
    Max,
    MetricAggregation,
    Min,
    Sum,
)
from cognite.client.data_classes.data_modeling import (
    View,
)

from industrial_model.models import TAggregatedViewInstance
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
        self, statement: AggregationStatement[TAggregatedViewInstance]
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
        metric_aggregation: MetricAggregation | None = None
        if statement.aggregate == "avg":
            metric_aggregation = Avg(statement.aggregation_property.property)
        elif statement.aggregate == "min":
            metric_aggregation = Min(statement.aggregation_property.property)
        elif statement.aggregate == "max":
            metric_aggregation = Max(statement.aggregation_property.property)
        elif statement.aggregate == "sum":
            metric_aggregation = Sum(statement.aggregation_property.property)
        elif statement.aggregate == "count":
            metric_aggregation = Count(statement.aggregation_property.property)

        if metric_aggregation is None:
            raise ValueError(
                f"Unsupported aggregate function: {statement.aggregate_}"
            )
        return AggregationQuery(
            view=root_view,
            metric_aggregation=metric_aggregation,
            filters=filters_,
            group_by_columns=statement.entity.get_group_by_fields(),
            limit=statement.limit_,
        )
