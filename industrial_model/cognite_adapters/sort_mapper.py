from cognite.client.data_classes.data_modeling import InstanceSort, MappedProperty, View

from industrial_model.cognite_adapters.utils import get_property_ref
from industrial_model.constants import SORT_DIRECTION
from industrial_model.statements.expressions import Column


class SortMapper:
    def map(
        self,
        sort_clauses: list[tuple[Column, SORT_DIRECTION]],
        root_view: View,
    ) -> list[InstanceSort]:
        return [
            InstanceSort(
                property=get_property_ref(column.property, root_view),
                direction=direction,
                nulls_first=self._is_nulls_first(column, root_view, direction),
            )
            for column, direction in sort_clauses
        ]

    def _is_nulls_first(
        self, column: Column, root_view: View, direction: SORT_DIRECTION
    ) -> bool:
        view_property = root_view.properties.get(column.property)

        if isinstance(view_property, MappedProperty) and view_property.source:
            return direction == "ascending"

        return direction == "descending"
