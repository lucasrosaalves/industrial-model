from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from cognite.client.data_classes.datapoint_aggregates import Aggregate
from cognite.client.data_classes.datapoints import Datapoints, DatapointsList

from industrial_model.calculator import (
    Calculator,
)
from industrial_model.calculator.formula_expression.exceptions import ParameterError
from industrial_model.calculator.models import (
    CalculationResult,
    CalculatorParameter,
    CalculatorQuery,
)
from industrial_model.models import InstanceId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 1, 2, tzinfo=UTC)


def _make_param(
    alias: str, space: str = "s", external_id: str = "x"
) -> CalculatorParameter:
    return CalculatorParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
    )


def _make_param_with_aggregate(
    alias: str,
    aggregate: Aggregate,
    granularity: str | None = None,
    space: str = "s",
    external_id: str = "x",
) -> CalculatorParameter:
    return CalculatorParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
        aggregate_type=aggregate,
        granularity=granularity,
    )


def _make_query(
    formula: str,
    parameters: list[CalculatorParameter],
) -> CalculatorQuery:
    return CalculatorQuery(
        formula=formula,
        parameters=parameters,
    )


def _make_datapoints(
    values: list[float] | None,
    space: str = "s",
    external_id: str = "x",
    timestamps: list[int] | None = None,
) -> Datapoints:
    return Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type="numeric",
        external_id=external_id,
        instance_id=MagicMock(space=space, external_id=external_id),
        timestamp=timestamps,
        value=values,
    )


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Calculator.calculate – shared helpers
# ---------------------------------------------------------------------------


def _make_datapoints_list(
    entries: dict[tuple[str, str], list[float]],
    timestamps: dict[tuple[str, str], list[int]] | None = None,
) -> MagicMock:
    """A stand-in for ``DatapointsList`` that resolves items by insertion-order index.

    Timestamps default to one-minute steps starting at ``_START`` so that every
    value falls inside the default ``[_START, _END)`` query window.
    """

    raw = MagicMock(spec=DatapointsList)
    base = _ms(_START)
    timestamps = timestamps or {}
    data_list = [
        _make_datapoints(
            values,
            space=instance[0],
            external_id=instance[1],
            timestamps=timestamps.get(
                instance, [base + i * 60_000 for i in range(len(values))]
            ),
        )
        for instance, values in entries.items()
    ]
    raw.__getitem__.side_effect = lambda idx: data_list[idx]
    return raw


def _client_returning(raw: MagicMock) -> MagicMock:
    client = MagicMock()
    client.time_series.data.retrieve.return_value = raw
    return client


def _make_aggregate_datapoints_list(
    instance: tuple[str, str],
    aggregate: str,
    values: list[float],
) -> MagicMock:
    """A ``DatapointsList`` stand-in holding a single aggregate series."""

    base = _ms(_START)
    dp = Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type="numeric",
        external_id=instance[1],
        instance_id=MagicMock(space=instance[0], external_id=instance[1]),
        timestamp=[base + i * 60_000 for i in range(len(values))],
    )
    setattr(dp, aggregate, values)
    raw = MagicMock(spec=DatapointsList)
    raw.__getitem__.side_effect = lambda idx: dp if idx == 0 else None
    return raw


# ---------------------------------------------------------------------------
# Calculator.calculate – happy paths
# ---------------------------------------------------------------------------


def test_calculate_returns_evaluation_result_for_simple_formula() -> None:
    param = _make_param("A", external_id="ts1")
    raw = _make_datapoints_list({("s", "ts1"): [1.0, 2.0, 3.0]})

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A} * 2", [param]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [2.0, 4.0, 6.0]


def test_calculate_passes_window_to_client() -> None:
    param = _make_param("A")
    raw = _make_datapoints_list({("s", "x"): [5.0]})

    client = _client_returning(raw)
    Calculator(client).calculate(_make_query("{A}", [param]), _START, _END)

    dp_query = client.time_series.data.retrieve.call_args.kwargs["instance_id"][0]
    assert dp_query.start == _START
    assert dp_query.end == _END


def test_calculate_multi_parameter_formula() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")

    raw = _make_datapoints_list(
        {("s", "ts_a"): [10.0, 20.0], ("s", "ts_b"): [2.0, 4.0]}
    )

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A} / {B}", [p_a, p_b]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [5.0, 5.0]


def test_calculate_with_aggregate_passes_granularity_in_query() -> None:
    param = _make_param_with_aggregate("A", aggregate="average", granularity="1h")
    raw = _make_aggregate_datapoints_list(("s", "x"), "average", [10.0, 20.0])

    client = _client_returning(raw)
    Calculator(client).calculate(_make_query("{A}", [param]), _START, _END)

    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert queries_arg[0].granularity == "1h"


def test_calculate_non_aggregate_parameter_has_no_granularity_in_query() -> None:
    param = _make_param("A")
    raw = _make_datapoints_list({("s", "x"): [1.0]})

    client = _client_returning(raw)
    Calculator(client).calculate(_make_query("{A}", [param]), _START, _END)

    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert queries_arg[0].granularity is None


def test_calculate_returns_empty_result_when_data_missing_for_parameter() -> None:
    param = _make_param("A")
    raw = _make_datapoints_list({("s", "x"): []})  # exists but has no values in window

    # A timeseries with no data in the window is treated as an empty series
    calc = Calculator(_client_returning(raw))
    query = _make_query("{A}", [param])
    result = calc.calculate(query, _START, _END)
    assert result == CalculationResult(query=query, datapoints=[])


# ---------------------------------------------------------------------------
# Calculator.calculate – deduplication
# ---------------------------------------------------------------------------


def test_calculate_deduplicates_identical_parameter_requests() -> None:
    # Two parameters in one formula referencing the same timeseries (same
    # aggregate/granularity) should be fetched a single time.
    p1 = _make_param("A", external_id="ts_a")
    p2 = _make_param("B", external_id="ts_a")

    raw = _make_datapoints_list({("s", "ts_a"): [3.0, 6.0]})
    client = _client_returning(raw)
    calc = Calculator(client)

    result = calc.calculate(_make_query("{A} + {B}", [p1, p2]), _START, _END)

    assert client.time_series.data.retrieve.call_count == 1
    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(queries_arg) == 1
    assert [dp.value for dp in result.datapoints] == [6.0, 12.0]


def test_calculate_raises_on_non_numeric_values_in_window() -> None:
    param = _make_param("A", external_id="ts_a")

    raw = _make_datapoints_list(
        {("s", "ts_a"): [1.0, "bad", 3.0]},  # type: ignore[list-item]
    )
    calc = Calculator(_client_returning(raw))

    with pytest.raises(ParameterError, match="parameter 'A' must be a numeric"):
        calc.calculate(_make_query("{A}", [param]), _START, _END)


# ---------------------------------------------------------------------------
# Calculator.calculate_multiples
# ---------------------------------------------------------------------------


def test_calculate_multiples_returns_one_result_per_query() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")

    raw = _make_datapoints_list(
        {("s", "ts_a"): [1.0, 2.0], ("s", "ts_b"): [10.0, 20.0]}
    )
    calc = Calculator(_client_returning(raw))

    results = calc.calculate_multiples(
        [_make_query("{A} * 2", [p_a]), _make_query("{B} + 1", [p_b])],
        _START,
        _END,
    )

    assert len(results) == 2
    assert [dp.value for dp in results[0].datapoints] == [2.0, 4.0]
    assert [dp.value for dp in results[1].datapoints] == [11.0, 21.0]


def test_calculate_multiples_batches_into_single_api_call() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")

    raw = _make_datapoints_list({("s", "ts_a"): [1.0], ("s", "ts_b"): [2.0]})
    client = _client_returning(raw)
    Calculator(client).calculate_multiples(
        [_make_query("{A}", [p_a]), _make_query("{B}", [p_b])],
        _START,
        _END,
    )

    assert client.time_series.data.retrieve.call_count == 1
    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(queries_arg) == 2


def test_calculate_multiples_deduplicates_shared_timeseries_across_queries() -> None:
    # Both queries reference the same time series — only one API request should
    # be made for it, but each query gets its own result.
    p_a = _make_param("A", external_id="ts_shared")
    p_b = _make_param("B", external_id="ts_shared")

    raw = _make_datapoints_list({("s", "ts_shared"): [5.0, 10.0]})
    client = _client_returning(raw)
    results = Calculator(client).calculate_multiples(
        [_make_query("{A} * 2", [p_a]), _make_query("{B} + 1", [p_b])],
        _START,
        _END,
    )

    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(queries_arg) == 1  # deduplicated to a single fetch
    assert [dp.value for dp in results[0].datapoints] == [10.0, 20.0]
    assert [dp.value for dp in results[1].datapoints] == [6.0, 11.0]


def test_calculate_multiples_empty_queries_returns_empty_list() -> None:
    client = MagicMock()
    results = Calculator(client).calculate_multiples([], _START, _END)

    assert results == []


def test_calculate_multiples_multi_parameter_query() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    p_c = _make_param("C", external_id="ts_c")

    raw = _make_datapoints_list(
        {
            ("s", "ts_a"): [4.0, 8.0],
            ("s", "ts_b"): [2.0, 4.0],
            ("s", "ts_c"): [1.0, 2.0],
        }
    )
    calc = Calculator(_client_returning(raw))

    results = calc.calculate_multiples(
        [
            _make_query("{A} / {B}", [p_a, p_b]),
            _make_query("{C} * 3", [p_c]),
        ],
        _START,
        _END,
    )

    assert [dp.value for dp in results[0].datapoints] == [2.0, 2.0]
    assert [dp.value for dp in results[1].datapoints] == [3.0, 6.0]
