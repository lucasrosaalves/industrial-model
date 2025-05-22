from cognite.client.data_classes.data_modeling import InstanceSort, View

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
                nulls_first=direction == "descending",
            )
            for column, direction in sort_clauses
        ]
