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

        statement_values = statement.get_values()
        filters_ = (
            filters.And(
                *self._filter_mapper.map(statement_values.where_clauses, root_view)
            )
            if statement_values.where_clauses
            else None
        )
        aggregation_property = statement_values.aggregation_property.property
        metric_aggregation: MetricAggregation | None = None
        if statement.aggregate == "avg":
            metric_aggregation = Avg(aggregation_property)
        elif statement.aggregate == "min":
            metric_aggregation = Min(aggregation_property)
        elif statement.aggregate == "max":
            metric_aggregation = Max(aggregation_property)
        elif statement.aggregate == "sum":
            metric_aggregation = Sum(aggregation_property)
        elif statement.aggregate == "count":
            metric_aggregation = Count(aggregation_property)

        if metric_aggregation is None:
            raise ValueError(f"Unsupported aggregate function: {statement.aggregate}")

        group_by_columns = (
            [prop.property for prop in statement_values.group_by_properties]
            if statement_values.group_by_properties is not None
            else statement.entity.get_group_by_fields()
        )
        return AggregationQuery(
            view=root_view,
            metric_aggregation=metric_aggregation,
            filters=filters_,
            group_by_columns=group_by_columns,
            limit=statement_values.limit,
        )
