from dataclasses import dataclass
from typing import Any

from industrial_model.constants import (
    BOOL_EXPRESSION_OPERATORS,
    LEAF_EXPRESSION_OPERATORS,
    SORT_DIRECTION,
)
from industrial_model.statements import BoolExpression, Expression, LeafExpression


@dataclass
class QueryParam:
    property: str
    operator: LEAF_EXPRESSION_OPERATORS

    def to_expression(self, value: Any) -> Expression:
        if self.operator == "nested":
            raise ValueError(
                "Nested operator not allowed in QueryParam - use NestedQueryParam"
            )

        if self.operator == "exists" and isinstance(value, bool) and not value:
            return BoolExpression(
                operator="not",
                filters=[
                    LeafExpression(
                        property=self.property, operator=self.operator, value=True
                    )
                ],
            )

        return LeafExpression(
            property=self.property,
            operator=self.operator,
            value=value,
        )


@dataclass
class NestedQueryParam:
    property: str
    value: QueryParam

    def to_expression(self, value: Any) -> Expression:
        return LeafExpression(
            property=self.property,
            operator="nested",
            value=self.value.to_expression(value),
        )


@dataclass
class BoolQueryParam:
    operator: BOOL_EXPRESSION_OPERATORS

    def to_expression(self, filters: list[Expression]) -> Expression:
        return BoolExpression(
            operator=self.operator,
            filters=filters,
        )


@dataclass
class SortParam:
    direction: SORT_DIRECTION
