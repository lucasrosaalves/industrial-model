from datetime import date, datetime

import cognite.client.data_classes.filters as cdf_filters
from cognite.client.data_classes.data_modeling import MappedProperty, View

from industrial_model.cognite_adapters.utils import get_property_ref
from industrial_model.statements import (
    BoolExpression,
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
                result.append(self.to_cdf_filter_bool(expression, root_view))
            elif isinstance(expression, LeafExpression):
                result.append(self.to_cdf_filter_leaf(expression, root_view))
            else:
                cls_name = expression.__class__.__name__
                raise ValueError(f"Expression not implemented {cls_name}")
        return result

    def to_cdf_filter_bool(
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

    def to_cdf_filter_leaf(
        self,
        expression: LeafExpression,
        root_view: View,
    ) -> cdf_filters.Filter:
        property_ref = get_property_ref(expression.property, root_view)

        value_ = expression.value
        if isinstance(value_, datetime):
            value_ = datetime_to_ms_iso_timestamp(value_)

        if isinstance(value_, date):
            value_ = value_.strftime("%Y-%m-%d")

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
            target_view = self._get_nested_target_view(
                expression.property, root_view
            )

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
        raise NotImplementedError(
            f"Operator {expression.operator} not implemented"
        )

    def _get_nested_target_view(self, property: str, root_view: View) -> View:
        view_definiton = root_view.properties[property]
        assert isinstance(view_definiton, MappedProperty)
        assert view_definiton.source
        return self._view_mapper.get_view(view_definiton.source.external_id)
