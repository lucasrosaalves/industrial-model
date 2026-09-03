from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from cognite.client.data_classes.datapoint_aggregates import Aggregate
from cognite.client.data_classes.datapoints import Datapoints

from industrial_model.calculator import (
    Calculator,
)
from industrial_model.calculator.formula_expression.exceptions import (
    MissingTimeAxisError,
    ParameterError,
    ParameterTimestampError,
)
from industrial_model.calculator.models import (
    AlignmentMode,
    CalculationResult,
    CalculatorParameter,
    CalculatorQuery,
    ConstantParameter,
    MultiTimeSeriesParameter,
    ReducerType,
    TimeSeriesParameter,
)
from industrial_model.models import InstanceId

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 1, 2, tzinfo=UTC)


def _make_param(
    alias: str, space: str = "s", external_id: str = "x"
) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
    )


def _make_multi_param(
    alias: str,
    instances: list[tuple[str, str]],
    reducer: ReducerType,
    aggregate: Aggregate | None = None,
    granularity: str | None = None,
) -> MultiTimeSeriesParameter:
    return MultiTimeSeriesParameter(
        alias=alias,
        timeseries_instance_ids=[
            InstanceId(space=space, external_id=external_id)
            for space, external_id in instances
        ],
        reducer=reducer,
        aggregate_type=aggregate,
        granularity=granularity,
    )


def _make_param_with_aggregate(
    alias: str,
    aggregate: Aggregate,
    granularity: str | None = None,
    space: str = "s",
    external_id: str = "x",
) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
        aggregate_type=aggregate,
        granularity=granularity,
    )


def _make_query(
    formula: str,
    parameters: list[CalculatorParameter],
    alignment: AlignmentMode = "intersect",
) -> CalculatorQuery:
    return CalculatorQuery(
        formula=formula,
        parameters=parameters,
        alignment=alignment,
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


def _input_values(result: CalculationResult) -> dict[str, list[float]]:
    return {
        alias: [dp.value for dp in series] for alias, series in result.inputs.items()
    }


def _assert_inputs_share_result_timestamps(result: CalculationResult) -> None:
    timestamps = [dp.timestamp for dp in result.datapoints]
    for series in result.inputs.values():
        assert [dp.timestamp for dp in series] == timestamps


# ---------------------------------------------------------------------------
# Calculator.calculate – shared helpers
# ---------------------------------------------------------------------------


def _make_datapoints_list(
    entries: dict[tuple[str, str], list[float]],
    timestamps: dict[tuple[str, str], list[int]] | None = None,
) -> list[Datapoints]:
    """A stand-in for ``DatapointsList`` that resolves items by insertion-order index.

    Timestamps default to one-minute steps starting at ``_START`` so that every
    value falls inside the default ``[_START, _END)`` query window.
    """

    base = _ms(_START)
    timestamps = timestamps or {}
    return [
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


def _client_returning(raw: list[Datapoints]) -> MagicMock:
    client = MagicMock()
    client.time_series.data.retrieve.return_value = raw
    return client


def _make_aggregate_datapoints_list(
    instance: tuple[str, str],
    aggregate: str,
    values: list[float],
) -> list[Datapoints]:
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
    return [dp]


# ---------------------------------------------------------------------------
# Calculator.calculate – happy paths
# ---------------------------------------------------------------------------


def test_calculate_returns_evaluation_result_for_simple_formula() -> None:
    param = _make_param("A", external_id="ts1")
    raw = _make_datapoints_list({("s", "ts1"): [1.0, 2.0, 3.0]})

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A} * 2", [param]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [2.0, 4.0, 6.0]


def test_calculate_rolling_average_keeps_input_alignment() -> None:
    param = _make_param("A", external_id="ts1")
    raw = _make_datapoints_list({("s", "ts1"): [10.0, 20.0, 30.0, 40.0]})

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(
        _make_query("rolling_average({A}, 3)", [param]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [10.0, 15.0, 20.0, 30.0]
    assert _input_values(result) == {"A": [10.0, 20.0, 30.0, 40.0]}
    _assert_inputs_share_result_timestamps(result)


def test_calculate_rolling_average_minus_second_series_stays_aligned() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    raw = _make_datapoints_list(
        {("s", "ts_a"): [10.0, 20.0, 30.0, 40.0], ("s", "ts_b"): [1.0, 2.0, 3.0, 4.0]}
    )

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(
        _make_query("rolling_average({A}, 3) - {B}", [p_a, p_b]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [9.0, 13.0, 17.0, 26.0]
    assert _input_values(result) == {
        "A": [10.0, 20.0, 30.0, 40.0],
        "B": [1.0, 2.0, 3.0, 4.0],
    }
    _assert_inputs_share_result_timestamps(result)


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
    assert result == CalculationResult(query=query, datapoints=[], inputs={"A": []})


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


# ---------------------------------------------------------------------------
# Calculator.calculate – constant parameters
# ---------------------------------------------------------------------------


def test_calculate_broadcasts_constant_parameter_to_series_length() -> None:
    ts_param = _make_param("A", external_id="ts_a")
    const_param = ConstantParameter(alias="B", value=10.0)

    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(
        _make_query("{A} + {B}", [ts_param, const_param]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [11.0, 12.0, 13.0]


def test_calculate_broadcasts_constant_onto_intersected_timestamps() -> None:
    ts_a = _make_param("A", external_id="ts_a")
    ts_b = _make_param("B", external_id="ts_b")
    const = ConstantParameter(alias="C", value=100.0)
    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0], ("s", "ts_b"): [10.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(
        _make_query("{A} + {B} + {C}", [ts_a, ts_b, const]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [111.0]


def test_calculate_constant_parameter_can_precede_timeseries_parameter() -> None:
    const_param = ConstantParameter(alias="B", value=2.0)
    ts_param = _make_param("A", external_id="ts_a")

    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(
        _make_query("{A} * {B}", [const_param, ts_param]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [2.0, 4.0]


def test_calculate_all_constant_formula_raises_missing_time_axis() -> None:
    # Constants are broadcast onto the timestamps of the query's timeseries
    # parameters. With no timeseries parameter there is nothing to broadcast
    # onto, which would silently yield zero datapoints for a query that looks
    # valid - so it is rejected instead.
    const_param = ConstantParameter(alias="A", value=5.0)

    calc = Calculator(MagicMock())
    query = _make_query("{A} * 2", [const_param])

    with pytest.raises(MissingTimeAxisError, match="no time-series parameter"):
        calc.calculate(query, _START, _END)


def test_missing_time_axis_error_lists_every_constant_alias() -> None:
    calc = Calculator(MagicMock())
    query = _make_query(
        "{A} + {B}",
        [
            ConstantParameter(alias="A", value=1.0),
            ConstantParameter(alias="B", value=2.0),
        ],
    )

    with pytest.raises(MissingTimeAxisError) as exc_info:
        calc.calculate(query, _START, _END)

    assert exc_info.value.aliases == ("A", "B")


# ---------------------------------------------------------------------------
# Calculator.calculate – multiple timeseries per parameter (reducers)
# ---------------------------------------------------------------------------


def test_calculate_reduces_multiple_timeseries_with_sum() -> None:
    param = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    base = _ms(_START)
    dp1 = _make_datapoints(
        None, space="s", external_id="ts1", timestamps=[base, base + 60_000]
    )
    dp1.average = [1.0, 2.0]
    dp2 = _make_datapoints(
        None, space="s", external_id="ts2", timestamps=[base, base + 60_000]
    )
    dp2.average = [10.0, 20.0]
    raw = [dp1, dp2]

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A}", [param]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [11.0, 22.0]


def test_calculate_reduces_multiple_timeseries_with_average() -> None:
    param = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="average",
        aggregate="average",
        granularity="1h",
    )
    base = _ms(_START)
    dp1 = _make_datapoints(None, space="s", external_id="ts1", timestamps=[base])
    dp1.average = [4.0]
    dp2 = _make_datapoints(None, space="s", external_id="ts2", timestamps=[base])
    dp2.average = [10.0]
    raw = [dp1, dp2]

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A}", [param]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [7.0]


def test_calculate_multi_instance_parameter_with_no_common_timestamps_is_empty() -> (
    None
):
    # The two series never overlap on timestamp, so the reduced parameter
    # series is empty end-to-end, and so is the result.
    param = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    base = _ms(_START)
    dp1 = _make_datapoints(None, space="s", external_id="ts1", timestamps=[base])
    dp1.average = [1.0]
    dp2 = _make_datapoints(
        None, space="s", external_id="ts2", timestamps=[base + 60_000]
    )
    dp2.average = [2.0]
    raw = [dp1, dp2]

    calc = Calculator(_client_returning(raw))
    query = _make_query("{A}", [param])
    result = calc.calculate(query, _START, _END)

    assert result == CalculationResult(query=query, datapoints=[], inputs={"A": []})


def test_calculate_timestamps_come_from_reduced_series_not_raw_leaf_series() -> None:
    # The first parameter is multi-instance: its two leaf series only agree
    # on one of their two timestamps, so the reduced series (and therefore
    # the output) has length 1, not the leaf series' length of 2.
    multi = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    single = _make_param_with_aggregate(
        "B", aggregate="average", granularity="1h", external_id="ts3"
    )

    base = _ms(_START)
    dp1 = _make_datapoints(
        None, space="s", external_id="ts1", timestamps=[base, base + 60_000]
    )
    dp1.average = [1.0, 2.0]
    dp2 = _make_datapoints(None, space="s", external_id="ts2", timestamps=[base])
    dp2.average = [10.0]
    dp3 = _make_datapoints(None, space="s", external_id="ts3", timestamps=[base])
    dp3.average = [100.0]
    raw = [dp1, dp2, dp3]

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A} + {B}", [multi, single]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [111.0]


def test_calculate_multiples_dedupes_shared_instance_across_multi_params() -> None:
    # Two queries each reference a two-instance reduced parameter, and the
    # two parameters share one instance id (ts_shared). That instance
    # should be fetched once, not twice.
    p_a = _make_multi_param(
        "A",
        [("s", "ts_shared"), ("s", "ts_a_only")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    p_b = _make_multi_param(
        "B",
        [("s", "ts_shared"), ("s", "ts_b_only")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )

    base = _ms(_START)

    def _dp(external_id: str, value: float) -> Datapoints:
        dp = _make_datapoints(
            None, space="s", external_id=external_id, timestamps=[base]
        )
        dp.average = [value]
        return dp

    series = [
        _dp("ts_shared", 1.0),
        _dp("ts_a_only", 2.0),
        _dp("ts_b_only", 3.0),
    ]

    client = _client_returning(series)
    results = Calculator(client).calculate_multiples(
        [_make_query("{A}", [p_a]), _make_query("{B}", [p_b])], _START, _END
    )

    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(queries_arg) == 3  # ts_shared, ts_a_only, ts_b_only - not 4
    assert [dp.value for dp in results[0].datapoints] == [3.0]  # 1.0 + 2.0
    assert [dp.value for dp in results[1].datapoints] == [4.0]  # 1.0 + 3.0


def test_calculate_multiples_honors_per_query_alignment() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    raw = _make_datapoints_list(
        {("s", "ts_a"): [1.0, 2.0], ("s", "ts_b"): [10.0, 20.0]}
    )
    calc = Calculator(_client_returning(raw))

    intersected, strict = calc.calculate_multiples(
        [
            _make_query("{A} + {B}", [p_a, p_b], alignment="intersect"),
            _make_query("{A} + {B}", [p_a, p_b], alignment="strict"),
        ],
        _START,
        _END,
    )

    assert [dp.value for dp in intersected.datapoints] == [11.0, 22.0]
    assert [dp.value for dp in strict.datapoints] == [11.0, 22.0]


def test_calculate_intersects_mismatched_series_by_default() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")

    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0], ("s", "ts_b"): [10.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(_make_query("{A} + {B}", [p_a, p_b]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [11.0]


def test_calculate_intersects_same_length_series_with_different_timestamps() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    base = _ms(_START)
    raw = _make_datapoints_list(
        {("s", "ts_a"): [1.0, 2.0], ("s", "ts_b"): [10.0, 20.0]},
        timestamps={
            ("s", "ts_a"): [base, base + 60_000],
            ("s", "ts_b"): [base + 60_000, base + 120_000],
        },
    )
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(_make_query("{A} + {B}", [p_a, p_b]), _START, _END)

    assert [dp.value for dp in result.datapoints] == [12.0]
    assert result.datapoints[0].timestamp == datetime.fromtimestamp(
        (base + 60_000) / 1000, tz=UTC
    )


def test_calculate_intersect_with_no_overlap_is_empty() -> None:
    multi = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    single = _make_param_with_aggregate(
        "B", aggregate="average", granularity="1h", external_id="ts3"
    )
    base = _ms(_START)
    dp1 = _make_datapoints(None, space="s", external_id="ts1", timestamps=[base])
    dp1.average = [1.0]
    dp2 = _make_datapoints(None, space="s", external_id="ts2", timestamps=[base])
    dp2.average = [10.0]
    dp3 = _make_datapoints(
        None, space="s", external_id="ts3", timestamps=[base + 60_000]
    )
    dp3.average = [100.0]

    query = _make_query("{A} + {B}", [multi, single])
    result = Calculator(_client_returning([dp1, dp2, dp3])).calculate(
        query, _START, _END
    )

    assert result == CalculationResult(
        query=query, datapoints=[], inputs={"A": [], "B": []}
    )


def test_calculate_strict_alignment_raises_on_mismatched_series() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")

    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0], ("s", "ts_b"): [1.0]})
    calc = Calculator(_client_returning(raw))

    with pytest.raises(ParameterTimestampError, match="timestamp mismatch"):
        calc.calculate(
            _make_query("{A} + {B}", [p_a, p_b], alignment="strict"),
            _START,
            _END,
        )


def test_calculate_strict_alignment_raises_when_same_length_but_different_times() -> (
    None
):
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    base = _ms(_START)
    raw = _make_datapoints_list(
        {("s", "ts_a"): [1.0, 2.0], ("s", "ts_b"): [10.0, 20.0]},
        timestamps={
            ("s", "ts_a"): [base, base + 60_000],
            ("s", "ts_b"): [base + 60_000, base + 120_000],
        },
    )
    calc = Calculator(_client_returning(raw))

    with pytest.raises(ParameterTimestampError, match="timestamp mismatch"):
        calc.calculate(
            _make_query("{A} + {B}", [p_a, p_b], alignment="strict"),
            _START,
            _END,
        )


def test_calculate_multiple_constants_never_reach_the_cdf_client() -> None:
    a = ConstantParameter(alias="A", value=2.0)
    b = ConstantParameter(alias="B", value=3.0)
    c = ConstantParameter(alias="C", value=4.0)
    ts = _make_param("D", external_id="ts_d")

    raw = _make_datapoints_list({("s", "ts_d"): [1.0, 1.0]})
    client = _client_returning(raw)
    calc = Calculator(client)

    result = calc.calculate(
        _make_query("{A} + {B} + {C} + {D}", [a, b, c, ts]), _START, _END
    )

    assert [dp.value for dp in result.datapoints] == [10.0, 10.0]
    # Only D's time series is ever requested - A, B, C never touch the client.
    queries_arg = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(queries_arg) == 1


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


# ---------------------------------------------------------------------------
# Calculator.calculate – inputs (aligned values used by the formula)
# ---------------------------------------------------------------------------


def test_calculate_inputs_are_the_series_passed_to_the_formula() -> None:
    param = _make_param("A", external_id="ts1")
    raw = _make_datapoints_list({("s", "ts1"): [1.0, 2.0, 3.0]})

    calc = Calculator(_client_returning(raw))
    result = calc.calculate(_make_query("{A} * 2", [param]), _START, _END)

    assert _input_values(result) == {"A": [1.0, 2.0, 3.0]}
    assert [dp.value for dp in result.datapoints] == [2.0, 4.0, 6.0]
    _assert_inputs_share_result_timestamps(result)


def test_calculate_inputs_include_every_parameter_at_aligned_indexes() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    raw = _make_datapoints_list(
        {("s", "ts_a"): [10.0, 20.0], ("s", "ts_b"): [2.0, 4.0]}
    )
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(_make_query("{A} / {B}", [p_a, p_b]), _START, _END)

    assert _input_values(result) == {"A": [10.0, 20.0], "B": [2.0, 4.0]}
    for i, dp in enumerate(result.datapoints):
        assert dp.value == result.inputs["A"][i].value / result.inputs["B"][i].value
    _assert_inputs_share_result_timestamps(result)


def test_calculate_inputs_are_the_intersected_values_not_the_raw_series() -> None:
    p_a = _make_param("A", external_id="ts_a")
    p_b = _make_param("B", external_id="ts_b")
    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0], ("s", "ts_b"): [10.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(_make_query("{A} + {B}", [p_a, p_b]), _START, _END)

    # Only the shared timestamp survives alignment, so inputs drop A's extra points.
    assert _input_values(result) == {"A": [1.0], "B": [10.0]}
    assert [dp.value for dp in result.datapoints] == [11.0]
    _assert_inputs_share_result_timestamps(result)


def test_calculate_inputs_broadcast_constants_to_the_aligned_length() -> None:
    ts_param = _make_param("A", external_id="ts_a")
    const_param = ConstantParameter(alias="B", value=10.0)
    raw = _make_datapoints_list({("s", "ts_a"): [1.0, 2.0, 3.0]})
    calc = Calculator(_client_returning(raw))

    result = calc.calculate(
        _make_query("{A} + {B}", [ts_param, const_param]), _START, _END
    )

    assert _input_values(result) == {
        "A": [1.0, 2.0, 3.0],
        "B": [10.0, 10.0, 10.0],
    }
    _assert_inputs_share_result_timestamps(result)


def test_calculate_inputs_use_the_reduced_series_for_multi_timeseries() -> None:
    param = _make_multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    base = _ms(_START)
    dp1 = _make_datapoints(
        None, space="s", external_id="ts1", timestamps=[base, base + 60_000]
    )
    dp1.average = [1.0, 2.0]
    dp2 = _make_datapoints(
        None, space="s", external_id="ts2", timestamps=[base, base + 60_000]
    )
    dp2.average = [10.0, 20.0]

    calc = Calculator(_client_returning([dp1, dp2]))
    result = calc.calculate(_make_query("{A}", [param]), _START, _END)

    assert _input_values(result) == {"A": [11.0, 22.0]}
    assert [dp.value for dp in result.datapoints] == [11.0, 22.0]
    _assert_inputs_share_result_timestamps(result)


def test_calculate_multiples_inputs_are_scoped_to_each_query() -> None:
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

    assert _input_values(results[0]) == {"A": [1.0, 2.0]}
    assert _input_values(results[1]) == {"B": [10.0, 20.0]}
    _assert_inputs_share_result_timestamps(results[0])
    _assert_inputs_share_result_timestamps(results[1])
