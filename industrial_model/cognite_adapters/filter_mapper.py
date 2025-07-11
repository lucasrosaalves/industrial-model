from datetime import date, datetime
from typing import Any

import cognite.client.data_classes.filters as cdf_filters
from cognite.client.data_classes.data_modeling import (
    EdgeConnection,
    MappedProperty,
    View,
)

from industrial_model.cognite_adapters.utils import get_property_ref
from industrial_model.models.entities import InstanceId
from industrial_model.statements import (
    BoolExpression,
    Column,
    Expression,
    LeafExpression,
)
from industrial_model.utils import datetime_to_ms_iso_timestamp

from .view_mapper import ViewMapper


class FilterMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper

    def map(
        self, expressions: list[Expression], root_view: View
    ) -> list[cdf_filters.Filter]:
        result: list[cdf_filters.Filter] = []
        for expression in expressions:
            if isinstance(expression, BoolExpression):
                result.append(self._to_cdf_filter_bool(expression, root_view))
            elif isinstance(expression, LeafExpression):
                result.append(self._to_cdf_filter_leaf(expression, root_view))
            else:
                cls_name = expression.__class__.__name__
                raise ValueError(f"Expression not implemented {cls_name}")
        return result

    def map_edges(
        self,
        edges_expressions: list[tuple[Column, list[Expression]]],
        root_view: View,
        nested_separator: str,
    ) -> dict[str, list[cdf_filters.Filter]]:
        result_dict: dict[str, list[cdf_filters.Filter]] = {}

        for column, expressions in edges_expressions:
            view_property = root_view.properties.get(column.property)
            if not isinstance(view_property, EdgeConnection):
                raise ValueError(f"Property {column.property} is not an edge")

            filters = self.map(
                expressions,
                self._view_mapper.get_view(view_property.source.external_id),
            )
            result_key = root_view.external_id + nested_separator + column.property
            result_dict.setdefault(result_key, []).extend(filters)

        return result_dict

    def _to_cdf_filter_bool(
        self, expression: BoolExpression, root_view: View
    ) -> cdf_filters.Filter:
        arguments = self.map(expression.filters, root_view)

        if expression.operator == "and":
            return cdf_filters.And(*arguments)
        elif expression.operator == "or":
            return cdf_filters.Or(*arguments)
        elif expression.operator == "not":
            return cdf_filters.Not(*arguments)

        raise NotImplementedError(f"Operator {self.operator} not implemented")

    def _to_cdf_filter_leaf(
        self,
        expression: LeafExpression,
        root_view: View,
    ) -> cdf_filters.Filter:
        property_ref = get_property_ref(expression.property, root_view)

        value_ = expression.value

        value_ = self._handle_type_value_convertion(value_)

        if expression.operator == "==":
            return cdf_filters.Equals(property_ref, value_)
        elif expression.operator == "in":
            return cdf_filters.In(property_ref, value_)
        elif expression.operator == ">":
            return cdf_filters.Range(property_ref, gt=value_)
        elif expression.operator == ">=":
            return cdf_filters.Range(property_ref, gte=value_)
        elif expression.operator == "<":
            return cdf_filters.Range(property_ref, lt=value_)
        elif expression.operator == "<=":
            return cdf_filters.Range(property_ref, lte=value_)
        elif expression.operator == "nested":
            target_view = self._get_nested_target_view(expression.property, root_view)

            assert isinstance(value_, Expression)

            return cdf_filters.Nested(
                property_ref,
                self.map([value_], target_view)[0],
            )
        elif expression.operator == "exists":
            return cdf_filters.Exists(property_ref)
        elif expression.operator == "prefix":
            return cdf_filters.Prefix(property_ref, value_)
        elif expression.operator == "containsAll":
            return cdf_filters.ContainsAll(property_ref, value_)
        elif expression.operator == "containsAny":
            return cdf_filters.ContainsAny(property_ref, value_)
        raise NotImplementedError(f"Operator {expression.operator} not implemented")

    def _get_nested_target_view(self, property: str, root_view: View) -> View:
        view_definiton = root_view.properties[property]
        assert isinstance(view_definiton, MappedProperty)
        assert view_definiton.source
        return self._view_mapper.get_view(view_definiton.source.external_id)

    def _handle_type_value_convertion(self, value_: Any) -> Any:
        if isinstance(value_, datetime):
            return datetime_to_ms_iso_timestamp(value_)
        elif isinstance(value_, date):
            return value_.strftime("%Y-%m-%d")
        elif isinstance(value_, InstanceId):
            return value_.model_dump(mode="json", by_alias=True)
        elif isinstance(value_, list):
            return [self._handle_type_value_convertion(v) for v in value_]
        return value_
