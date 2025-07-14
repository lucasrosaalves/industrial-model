import cognite.client.data_classes.filters as filters
from cognite.client.data_classes.data_modeling import (
    EdgeConnection,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.query import (
    EdgeResultSetExpression,
    NodeResultSetExpression,
    ResultSetExpression,
    Select,
    SourceSelector,
)
from cognite.client.data_classes.data_modeling.query import (
    Query as CogniteQuery,
)
from cognite.client.data_classes.data_modeling.views import (
    MultiReverseDirectRelation,
    SingleReverseDirectRelation,
)

from industrial_model.constants import EDGE_MARKER, MAX_LIMIT, NESTED_SEP
from industrial_model.models import TViewInstance, get_schema_properties
from industrial_model.statements import Statement

from .filter_mapper import (
    FilterMapper,
)
from .sort_mapper import SortMapper
from .view_mapper import ViewMapper


class QueryMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper
        self._filter_mapper = FilterMapper(view_mapper)
        self._sort_mapper = SortMapper()

    def map(self, statement: Statement[TViewInstance]) -> CogniteQuery:
        root_node = statement.entity.get_view_external_id()

        root_view = self._view_mapper.get_view(root_node)
        root_view_id = root_view.as_id()

        filters_: list[filters.Filter] = [filters.HasData(views=[root_view_id])]

        statement_values = statement.get_values()
        filters_.extend(
            self._filter_mapper.map(statement_values.where_clauses, root_view)
        )

        with_: dict[str, ResultSetExpression] = {
            root_node: NodeResultSetExpression(
                filter=filters.And(*filters_),
                sort=self._sort_mapper.map(statement_values.sort_clauses, root_view),
                limit=statement_values.limit,
            )
        }
        select_: dict[str, Select] = {}

        relations = get_schema_properties(statement.entity, NESTED_SEP, root_node)

        edge_filters = self._filter_mapper.map_edges(
            statement_values.where_edge_clauses, root_view, NESTED_SEP
        )

        properties = self._include_statements(
            root_node, root_view, relations, edge_filters, with_, select_
        )

        select_[root_node] = self._get_select(root_view_id, properties)

        return CogniteQuery(
            with_=with_,
            select=select_,
            cursors={root_node: statement_values.cursor},
        )

    def _get_select(self, view_id: ViewId, properties: list[str]) -> Select:
        return (
            Select(sources=[SourceSelector(source=view_id, properties=properties)])
            if properties
            else Select()
        )

    def _include_statements(
        self,
        key: str,
        view: View,
        relations_to_include: list[str] | None,
        edge_filters: dict[str, list[filters.Filter]],
        with_: dict[str, ResultSetExpression],
        select_: dict[str, Select],
    ) -> list[str]:
        if not relations_to_include:
            return []

        select_properties: list[str] = []
        for property_name, property in view.properties.items():
            property_key = f"{key}{NESTED_SEP}{property_name}"
            if property_key not in relations_to_include:
                continue

            if isinstance(property, MappedProperty) and not property.source:
                select_properties.append(property_name)
            elif isinstance(property, MappedProperty) and property.source:
                select_properties.append(property_name)

                props = self._include_statements(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    relations_to_include,
                    edge_filters,
                    with_,
                    select_,
                )
                if props:
                    with_[property_key] = NodeResultSetExpression(
                        from_=key,
                        through=view.as_property_ref(property_name),
                        limit=MAX_LIMIT,
                    )
                    select_[property_key] = self._get_select(property.source, props)

            elif (
                isinstance(property, MultiReverseDirectRelation)
                or isinstance(property, SingleReverseDirectRelation)
                and property.source
            ):
                props = self._include_statements(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    relations_to_include,
                    edge_filters,
                    with_,
                    select_,
                )

                with_[property_key] = NodeResultSetExpression(
                    from_=key,
                    direction="inwards",
                    through=property.source.as_property_ref(property.through.property),
                    limit=MAX_LIMIT,
                )

                if property.through.property not in props:
                    props.append(property.through.property)

                select_[property_key] = self._get_select(property.source, props)
            elif isinstance(property, EdgeConnection) and property.source:
                edge_property_key = f"{property_key}{NESTED_SEP}{EDGE_MARKER}"

                edge_filter = edge_filters.get(property_key)

                with_[edge_property_key] = EdgeResultSetExpression(
                    from_=key,
                    max_distance=1,
                    filter=filters.Equals(
                        ["edge", "type"],
                        property.type.dump(),
                    ),
                    node_filter=filters.And(*edge_filter) if edge_filter else None,
                    direction=property.direction,
                    limit=MAX_LIMIT,
                )
                with_[property_key] = NodeResultSetExpression(
                    from_=edge_property_key,
                    limit=MAX_LIMIT,
                )

                select_[edge_property_key] = Select()

                props = self._include_statements(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    relations_to_include,
                    edge_filters,
                    with_,
                    select_,
                )
                select_[property_key] = self._get_select(property.source, props)

        return select_properties
