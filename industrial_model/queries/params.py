from dataclasses import dataclass
from typing import Any

from industrial_model.constants import (
    LEAF_EXPRESSION_OPERATORS,
    SORT_DIRECTION,
)
from industrial_model.statements import LeafExpression


@dataclass
class QueryParam:
    property: str
    operator: LEAF_EXPRESSION_OPERATORS

    def to_expression(self, value: Any) -> LeafExpression:
        if self.operator == "nested":
            raise ValueError("Can not have nested operator on QuertParam")

        return LeafExpression(
            property=self.property,
            operator=self.operator,
            value=value,
        )


@dataclass
class NestedQueryParam:
    property: str
    value: QueryParam

    def to_expression(self, value: Any) -> LeafExpression:
        return LeafExpression(
            property=self.property,
            operator="nested",
            value=self.value.to_expression(value),
        )


@dataclass
class SortParam:
    direction: SORT_DIRECTION
