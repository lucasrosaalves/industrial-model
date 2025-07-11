from typing import Any

from industrial_model.constants import SORT_DIRECTION
from industrial_model.models import RootModel
from industrial_model.statements import Expression

from .params import BoolQueryParam, NestedQueryParam, QueryParam, SortParam


def extract_base_statement_params(
    entity: RootModel,
) -> tuple[list[Expression], list[tuple[Any, SORT_DIRECTION]]]:
    filters_: list[Expression] = []
    sort_params: list[tuple[Any, SORT_DIRECTION]] = []

    for key, item in entity.__class__.model_fields.items():
        values = getattr(entity, key)
        if values is None:
            continue
        for metadata_item in item.metadata:
            if isinstance(metadata_item, SortParam):
                sort_params.append((values, metadata_item.direction))
            elif isinstance(
                metadata_item, QueryParam | NestedQueryParam | BoolQueryParam
            ):
                filter_ = _extract_expression(metadata_item, values)
                if filter_ is not None:
                    filters_.append(filter_)
    return filters_, sort_params


def _extract_expression(
    metadata_item: QueryParam | NestedQueryParam | BoolQueryParam, values: Any
) -> Expression | None:
    if isinstance(metadata_item, QueryParam | NestedQueryParam):
        return metadata_item.to_expression(values)

    if not isinstance(values, RootModel):
        return None

    filters_, _ = extract_base_statement_params(values)
    return metadata_item.to_expression(filters_)
