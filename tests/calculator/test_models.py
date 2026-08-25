from __future__ import annotations

import pytest
from pydantic import ValidationError

from industrial_model.calculator.models import (
    CalculatorQuery,
    ConstantParameter,
    MultiTimeSeriesParameter,
    ReducerType,
    TimeSeriesParameter,
)
from industrial_model.models import InstanceId

# ---------------------------------------------------------------------------
# Discriminator defaults
# ---------------------------------------------------------------------------


def test_constant_parameter_defaults_type_to_constant() -> None:
    param = ConstantParameter(alias="A", value=1.0)

    assert param.type == "constant"


def test_single_timeseries_parameter_defaults_type() -> None:
    param = TimeSeriesParameter(
        alias="A", timeseries_instance_id=InstanceId(space="s", external_id="x")
    )

    assert param.type == "single_timeseries"


def test_multi_timeseries_parameter_defaults_type() -> None:
    param = MultiTimeSeriesParameter(
        alias="A",
        timeseries_instance_ids=[
            InstanceId(space="s", external_id="x1"),
            InstanceId(space="s", external_id="x2"),
        ],
        reducer="sum",
    )

    assert param.type == "multi_timeseries"


# ---------------------------------------------------------------------------
# Discriminated union parsing (CalculatorQuery.model_validate)
# ---------------------------------------------------------------------------


def test_model_validate_resolves_parameters_by_type_tag() -> None:
    payload = {
        "formula": "{A} + {B} + {C}",
        "parameters": [
            {
                "type": "single_timeseries",
                "alias": "A",
                "timeseries_instance_id": {"space": "s", "external_id": "x"},
            },
            {"type": "constant", "alias": "B", "value": 1.0},
            {
                "type": "multi_timeseries",
                "alias": "C",
                "timeseries_instance_ids": [
                    {"space": "s", "external_id": "x1"},
                    {"space": "s", "external_id": "x2"},
                ],
                "reducer": "sum",
            },
        ],
    }

    query = CalculatorQuery.model_validate(payload)

    assert isinstance(query.parameters[0], TimeSeriesParameter)
    assert isinstance(query.parameters[1], ConstantParameter)
    assert isinstance(query.parameters[2], MultiTimeSeriesParameter)


def test_model_validate_without_type_tag_raises_validation_error() -> None:
    # A dict built by hand (e.g. from an external API payload) that omits the
    # discriminator can't be resolved to any parameter class, even though
    # ``type`` has a default when constructing a class directly in Python.
    payload = {
        "formula": "{A}",
        "parameters": [
            {
                "alias": "A",
                "timeseries_instance_id": {"space": "s", "external_id": "x"},
            }
        ],
    }

    with pytest.raises(ValidationError, match="Unable to extract tag"):
        CalculatorQuery.model_validate(payload)


def test_model_dump_then_model_validate_round_trips() -> None:
    query = CalculatorQuery(
        formula="{A} + {B}",
        parameters=[
            TimeSeriesParameter(
                alias="A", timeseries_instance_id=InstanceId(space="s", external_id="x")
            ),
            ConstantParameter(alias="B", value=2.0),
        ],
    )

    round_tripped = CalculatorQuery.model_validate(query.model_dump())

    assert round_tripped == query
    assert isinstance(round_tripped.parameters[0], TimeSeriesParameter)
    assert isinstance(round_tripped.parameters[1], ConstantParameter)


# ---------------------------------------------------------------------------
# MultiTimeSeriesParameter validation
# ---------------------------------------------------------------------------


def test_multi_timeseries_parameter_rejects_empty_instance_id_list() -> None:
    with pytest.raises(ValidationError, match="at least two timeseries"):
        MultiTimeSeriesParameter(alias="A", timeseries_instance_ids=[], reducer="sum")


def test_multi_timeseries_parameter_rejects_a_single_instance_id() -> None:
    # A single time series should be expressed as TimeSeriesParameter.
    with pytest.raises(ValidationError, match="at least two timeseries"):
        MultiTimeSeriesParameter(
            alias="A",
            timeseries_instance_ids=[InstanceId(space="s", external_id="x")],
            reducer="sum",
        )


def test_multi_timeseries_parameter_requires_reducer_field() -> None:
    with pytest.raises(ValidationError, match="reducer"):
        MultiTimeSeriesParameter.model_validate(
            {
                "alias": "A",
                "timeseries_instance_ids": [
                    {"space": "s", "external_id": "x1"},
                    {"space": "s", "external_id": "x2"},
                ],
            }
        )


def test_multi_timeseries_parameter_rejects_duplicate_instance_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate timeseries instance ids"):
        MultiTimeSeriesParameter(
            alias="A",
            timeseries_instance_ids=[
                InstanceId(space="s", external_id="x1"),
                InstanceId(space="s", external_id="x1"),
            ],
            reducer="sum",
        )


def test_aggregate_without_granularity_is_rejected_at_construction() -> None:
    with pytest.raises(ValidationError, match="Missing granularity for 'A'"):
        TimeSeriesParameter(
            alias="A",
            timeseries_instance_id=InstanceId(space="s", external_id="x"),
            aggregate_type="average",
        )


def test_multi_timeseries_aggregate_without_granularity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Missing granularity for 'A'"):
        MultiTimeSeriesParameter(
            alias="A",
            timeseries_instance_ids=[
                InstanceId(space="s", external_id="x1"),
                InstanceId(space="s", external_id="x2"),
            ],
            aggregate_type="sum",
            reducer="sum",
        )


def test_multi_timeseries_parameter_with_two_ids_and_reducer_is_valid() -> None:
    param = MultiTimeSeriesParameter(
        alias="A",
        timeseries_instance_ids=[
            InstanceId(space="s", external_id="x1"),
            InstanceId(space="s", external_id="x2"),
        ],
        reducer="average",
    )

    assert len(param.timeseries_instance_ids) == 2


def test_single_timeseries_parameter_has_no_reducer_field() -> None:
    param = TimeSeriesParameter(
        alias="A", timeseries_instance_id=InstanceId(space="s", external_id="x")
    )

    assert not hasattr(param, "reducer")
    assert param.instance_ids() == (InstanceId(space="s", external_id="x"),)


def test_multi_timeseries_parameter_instance_ids_preserves_order() -> None:
    ids = [
        InstanceId(space="s", external_id="x1"),
        InstanceId(space="s", external_id="x2"),
    ]
    param = MultiTimeSeriesParameter(
        alias="A",
        timeseries_instance_ids=ids,
        reducer="sum",
    )

    assert list(param.instance_ids()) == ids


# ---------------------------------------------------------------------------
# ReducerType / AlignmentMode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reducer", ["min", "max", "sum", "average"])
def test_reducer_type_accepts_each_literal(reducer: ReducerType) -> None:
    param = MultiTimeSeriesParameter(
        alias="A",
        timeseries_instance_ids=[
            InstanceId(space="s", external_id="x1"),
            InstanceId(space="s", external_id="x2"),
        ],
        reducer=reducer,
    )

    assert param.reducer == reducer


def test_reducer_type_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        MultiTimeSeriesParameter(
            alias="A",
            timeseries_instance_ids=[
                InstanceId(space="s", external_id="x1"),
                InstanceId(space="s", external_id="x2"),
            ],
            reducer="median",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# CalculatorQuery – duplicate alias validation
# ---------------------------------------------------------------------------


def test_calculator_query_rejects_duplicate_aliases() -> None:
    with pytest.raises(ValidationError, match="duplicate parameter alias"):
        CalculatorQuery(
            formula="{A} + {A}",
            parameters=[
                ConstantParameter(alias="A", value=1.0),
                ConstantParameter(alias="A", value=2.0),
            ],
        )


def test_calculator_query_rejects_duplicate_aliases_across_parameter_types() -> None:
    with pytest.raises(ValidationError, match="duplicate parameter alias"):
        CalculatorQuery(
            formula="{A}",
            parameters=[
                ConstantParameter(alias="A", value=1.0),
                TimeSeriesParameter(
                    alias="A",
                    timeseries_instance_id=InstanceId(space="s", external_id="x"),
                ),
            ],
        )


def test_calculator_query_error_lists_every_duplicate_alias() -> None:
    with pytest.raises(ValidationError, match="A") as exc_info:
        CalculatorQuery(
            formula="{A} + {B}",
            parameters=[
                ConstantParameter(alias="A", value=1.0),
                ConstantParameter(alias="A", value=2.0),
                ConstantParameter(alias="B", value=3.0),
                ConstantParameter(alias="B", value=4.0),
            ],
        )

    message = str(exc_info.value)
    assert "A" in message
    assert "B" in message


def test_calculator_query_allows_unique_aliases() -> None:
    query = CalculatorQuery(
        formula="{A} + {B}",
        parameters=[
            ConstantParameter(alias="A", value=1.0),
            ConstantParameter(alias="B", value=2.0),
        ],
    )

    assert [p.alias for p in query.parameters] == ["A", "B"]


def test_calculator_query_allows_a_single_parameter() -> None:
    query = CalculatorQuery(
        formula="{A}", parameters=[ConstantParameter(alias="A", value=1.0)]
    )

    assert len(query.parameters) == 1


def test_calculator_query_allows_zero_parameters() -> None:
    # No aliases at all means no duplicates - the formula engine, not this
    # validator, is responsible for rejecting a parameter-less formula.
    query = CalculatorQuery(formula="42", parameters=[])

    assert query.parameters == []


def test_calculator_query_defaults_alignment_to_intersect() -> None:
    query = CalculatorQuery(
        formula="{A}", parameters=[ConstantParameter(alias="A", value=1.0)]
    )

    assert query.alignment == "intersect"


def test_calculator_query_accepts_strict_alignment_string() -> None:
    query = CalculatorQuery(
        formula="{A}",
        parameters=[ConstantParameter(alias="A", value=1.0)],
        alignment="strict",
    )

    assert query.alignment == "strict"


def test_calculator_query_rejects_unknown_alignment() -> None:
    with pytest.raises(ValidationError):
        CalculatorQuery(
            formula="{A}",
            parameters=[ConstantParameter(alias="A", value=1.0)],
            alignment="union",  # type: ignore[arg-type]
        )
