"""``Calculator`` with ``sum(...)`` / ``average(...)`` formulas.

Parameters are fetched exactly as declared (here per minute), the formula
runs on them, and the results are aggregated by the query's
``bucket_granularity``. The running example is OEE Speed Losses Time,
``(NSP * RUNT - TTP) / NSP``, whose hourly value is only right when the
division happens per minute.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from cognite.client.data_classes.datapoint_aggregates import Aggregate
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from industrial_model.calculator import Calculator
from industrial_model.calculator.exceptions import BucketGranularityError
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
    MissingTimeAxisError,
)
from industrial_model.calculator.models import (
    CalculationResult,
    CalculatorParameter,
    CalculatorQuery,
    ConstantParameter,
    MultiTimeSeriesParameter,
    TimeSeriesParameter,
)
from industrial_model.models import InstanceId

_START = datetime(2026, 4, 15, 10, tzinfo=UTC)
_END = _START + timedelta(hours=2)
_SLT = "sum((({NSP} * {RUNT}) - {TTP}) / {NSP})"

_Points = list[tuple[datetime, float]]


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _to_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    assert isinstance(value, int)
    return datetime.fromtimestamp(value / 1000, tz=UTC)


class _FakeCdf:
    """Answers datapoints retrieves from in-memory series, recording each call.

    ``series`` maps ``(external_id, granularity)`` to points. The same points
    are served for whatever aggregate is asked, which is what a per-minute
    curated series looks like at ``1m``.
    """

    def __init__(self, series: dict[tuple[str, str | None], _Points]) -> None:
        self.series = series
        self.calls: list[list[_Request]] = []
        self.client = MagicMock()
        self.client.time_series.data.retrieve = self._retrieve
        self.client.get_async_client.return_value = self.client

    async def _retrieve(self, instance_id: Sequence[DatapointsQuery]) -> list[Any]:
        queries = list(instance_id)
        self.calls.append([_snapshot(query) for query in queries])
        return [self._answer(query) for query in queries]

    def _answer(self, query: DatapointsQuery) -> Datapoints:
        external_id = _external_id(query)
        granularity = query.granularity if isinstance(query.granularity, str) else None
        start = _to_datetime(query.start)
        end = _to_datetime(query.end)
        points = [
            (ts, value)
            for ts, value in self.series.get((external_id, granularity), [])
            if start <= ts < end
        ]
        dp = Datapoints(
            id=1,
            is_string=False,
            is_step=False,
            type="numeric",
            external_id=external_id,
            instance_id=MagicMock(space="s", external_id=external_id),
            timestamp=[_ms(ts) for ts, _ in points],
        )
        values = [value for _, value in points]
        if granularity is None:
            dp.value = values
        else:
            aggregates = query.aggregates
            assert isinstance(aggregates, list)
            for name in aggregates:
                setattr(dp, str(name), values)
        return dp


@dataclass(frozen=True)
class _Request:
    """What one datapoints query asked for, captured before paging moves it."""

    external_id: str
    start: datetime
    end: datetime
    granularity: str | None
    aggregates: list[str] | None
    timezone: str | None


def _external_id(query: DatapointsQuery) -> str:
    return str(query.identifier.as_primitive().external_id)


def _snapshot(query: DatapointsQuery) -> _Request:
    return _Request(
        external_id=_external_id(query),
        start=_to_datetime(query.start),
        end=_to_datetime(query.end),
        granularity=query.granularity if isinstance(query.granularity, str) else None,
        aggregates=list(query.aggregates)
        if isinstance(query.aggregates, list)
        else None,
        timezone=query.timezone if isinstance(query.timezone, str) else None,
    )


def _param(
    alias: str,
    external_id: str,
    aggregate: Aggregate | None = "sum",
    granularity: str | None = "1m",
    fill_value: float | None = None,
) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space="s", external_id=external_id),
        aggregate_type=aggregate,
        granularity=granularity if aggregate is not None else None,
        fill_value=fill_value,
    )


def _slt_parameters(
    granularity: str = "1m", fill_value: float | None = None
) -> list[CalculatorParameter]:
    return [
        _param("NSP", "nsp", "average", granularity),
        _param("RUNT", "runt", "sum", granularity, fill_value),
        _param("TTP", "ttp", "sum", granularity, fill_value),
    ]


def _hourly(formula: str, parameters: list[CalculatorParameter]) -> CalculatorQuery:
    return CalculatorQuery(
        formula=formula, parameters=parameters, bucket_granularity="1h"
    )


def _per_minute(
    start: datetime, end: datetime, value: Callable[[datetime], float | None]
) -> _Points:
    points: _Points = []
    moment = start
    while moment < end:
        item = value(moment)
        if item is not None:
            points.append((moment, item))
        moment += timedelta(minutes=1)
    return points


def _nominal_speed(moment: datetime) -> float:
    # The product changes on the half hour: 10 units/min, then 20.
    return 10.0 if moment.minute < 30 else 20.0


def _slt_cdf(
    start: datetime = _START,
    end: datetime = _END,
    throughput: Callable[[datetime], float | None] = lambda _: 8.0,
) -> _FakeCdf:
    return _FakeCdf(
        {
            ("nsp", "1m"): _per_minute(start, end, _nominal_speed),
            ("runt", "1m"): _per_minute(start, end, lambda _: 1.0),
            ("ttp", "1m"): _per_minute(start, end, throughput),
        }
    )


def _calculate(
    cdf: _FakeCdf,
    query: CalculatorQuery,
    start: datetime = _START,
    end: datetime = _END,
    timezone: str | None = None,
) -> CalculationResult:
    return asyncio.run(
        Calculator(cdf.client).calculate(query, start, end, timezone=timezone)
    )


def _values(result: CalculationResult) -> list[tuple[datetime, object]]:
    return [(dp.timestamp, pytest.approx(dp.value)) for dp in result.datapoints]


# ---------------------------------------------------------------------------
# Calculate on the parameters as fetched, then aggregate
# ---------------------------------------------------------------------------


def test_sum_runs_per_fetched_point_then_sums_each_bucket() -> None:
    # Per minute: 1 - 8/10 = 0.2 for 30 minutes, 1 - 8/20 = 0.6 for 30.
    # Aggregating first would give (15 * 60 - 480) / 15 = 28 per hour.
    result = _calculate(_slt_cdf(), _hourly(_SLT, _slt_parameters()))

    assert _values(result) == [
        (_START, 24.0),
        (_START + timedelta(hours=1), 24.0),
    ]


def test_average_runs_per_fetched_point_then_averages_each_bucket() -> None:
    result = _calculate(
        _slt_cdf(), _hourly("average({TTP} / {NSP})", _slt_parameters())
    )

    assert _values(result) == [
        (_START, 0.6),
        (_START + timedelta(hours=1), 0.6),
    ]


def test_parameters_are_fetched_exactly_as_declared() -> None:
    cdf = _slt_cdf()

    _calculate(
        cdf,
        _hourly(_SLT, _slt_parameters()),
        start=_START + timedelta(minutes=37),
        end=_START + timedelta(hours=1, minutes=5),
    )

    assert len(cdf.calls) == 1
    queries = cdf.calls[0]
    assert {query.granularity for query in queries} == {"1m"}
    assert [query.aggregates for query in queries] == [
        ["average"],
        ["sum"],
        ["sum"],
    ]
    # The window covers the whole hourly buckets that [start, end) touches.
    assert {query.start for query in queries} == {_START}
    assert {query.end for query in queries} == {_END}


def test_mid_bucket_window_returns_whole_buckets_like_cdf() -> None:
    result = _calculate(
        _slt_cdf(),
        _hourly(_SLT, _slt_parameters()),
        start=_START + timedelta(minutes=37),
        end=_START + timedelta(hours=1, minutes=5),
    )

    assert _values(result) == [
        (_START, 24.0),
        (_START + timedelta(hours=1), 24.0),
    ]


def test_parameters_at_another_granularity() -> None:
    cdf = _FakeCdf(
        {
            ("runt", "15m"): [
                (_START + timedelta(minutes=15 * i), 15.0) for i in range(8)
            ],
        }
    )

    result = _calculate(
        cdf, _hourly("sum({RUNT} / 15)", [_param("RUNT", "runt", "sum", "15m")])
    )

    assert {query.granularity for query in cdf.calls[0]} == {"15m"}
    assert _values(result) == [
        (_START, 4.0),
        (_START + timedelta(hours=1), 4.0),
    ]


def test_raw_parameters_are_calculated_per_raw_point() -> None:
    stamps = [_START + timedelta(seconds=s) for s in (5, 20, 3_610, 3_650)]
    cdf = _FakeCdf(
        {
            ("good", None): [(ts, 4.0) for ts in stamps],
            ("scrap", None): [(ts, 1.0) for ts in stamps],
        }
    )

    result = _calculate(
        cdf,
        _hourly(
            "sum({SQ} / ({GQ} + {SQ}))",
            [_param("GQ", "good", None), _param("SQ", "scrap", None)],
        ),
    )

    assert {query.granularity for query in cdf.calls[0]} == {None}
    assert _values(result) == [
        (_START, 0.4),
        (_START + timedelta(hours=1), 0.4),
    ]


def test_constants_are_broadcast_per_fetched_point() -> None:
    result = _calculate(
        _slt_cdf(),
        _hourly(
            "sum({RUNT} * {SECONDS})",
            [
                _param("RUNT", "runt"),
                ConstantParameter(alias="SECONDS", value=60.0),
            ],
        ),
    )

    assert _values(result) == [
        (_START, 3_600.0),
        (_START + timedelta(hours=1), 3_600.0),
    ]


def test_multi_timeseries_parameter_is_reduced_per_fetched_point() -> None:
    cdf = _FakeCdf(
        {
            ("nsp", "1m"): _per_minute(_START, _END, _nominal_speed),
            ("good", "1m"): _per_minute(_START, _END, lambda _: 6.0),
            ("scrap", "1m"): _per_minute(_START, _END, lambda _: 2.0),
        }
    )
    throughput = MultiTimeSeriesParameter(
        alias="TTP",
        timeseries_instance_ids=[
            InstanceId(space="s", external_id="good"),
            InstanceId(space="s", external_id="scrap"),
        ],
        reducer="sum",
        aggregate_type="sum",
        granularity="1m",
    )

    result = _calculate(
        cdf,
        _hourly("sum({TTP} / {NSP})", [_param("NSP", "nsp", "average"), throughput]),
    )

    # 8/10 for 30 minutes + 8/20 for 30 minutes.
    assert _values(result) == [
        (_START, 36.0),
        (_START + timedelta(hours=1), 36.0),
    ]


def test_multi_timeseries_fill_value_keeps_a_line_that_reported() -> None:
    # Scrap reports nothing for the first ten minutes of each hour; good
    # parts from those minutes must still count.
    cdf = _FakeCdf(
        {
            ("nsp", "1m"): _per_minute(_START, _END, _nominal_speed),
            ("good", "1m"): _per_minute(_START, _END, lambda _: 6.0),
            ("scrap", "1m"): _per_minute(
                _START, _END, lambda m: None if m.minute < 10 else 2.0
            ),
        }
    )
    throughput = MultiTimeSeriesParameter(
        alias="TTP",
        timeseries_instance_ids=[
            InstanceId(space="s", external_id="good"),
            InstanceId(space="s", external_id="scrap"),
        ],
        reducer="sum",
        aggregate_type="sum",
        granularity="1m",
        fill_value=0,
    )

    result = _calculate(
        cdf, _hourly("sum({TTP})", [_param("NSP", "nsp", "average"), throughput])
    )

    # 10 minutes * 6 + 50 minutes * 8.
    assert _values(result) == [
        (_START, 460.0),
        (_START + timedelta(hours=1), 460.0),
    ]


def test_guarded_division_runs_per_fetched_point() -> None:
    cdf = _FakeCdf(
        {
            ("nsp", "1m"): _per_minute(
                _START, _END, lambda m: 0.0 if m.minute < 30 else 20.0
            ),
            ("ttp", "1m"): _per_minute(_START, _END, lambda _: 8.0),
        }
    )

    result = _calculate(
        cdf,
        _hourly(
            "sum({TTP} / {NSP} if {NSP} != 0 else 0)",
            [_param("NSP", "nsp", "average"), _param("TTP", "ttp")],
        ),
    )

    assert _values(result) == [
        (_START, 12.0),
        (_START + timedelta(hours=1), 12.0),
    ]


# ---------------------------------------------------------------------------
# Several bucket terms: aggregate each, then run the formula per bucket
# ---------------------------------------------------------------------------

_PERFORMANCE = "sum({TTP}) / sum({NSP} * {RUNT})"


def test_ratio_of_bucket_sums_divides_once_per_bucket() -> None:
    result = _calculate(_slt_cdf(), _hourly(_PERFORMANCE, _slt_parameters()))

    # 480 produced over 30 * 10 + 30 * 20 = 900 possible.
    assert _values(result) == [
        (_START, 480 / 900),
        (_START + timedelta(hours=1), 480 / 900),
    ]


def test_average_of_ratios_is_not_the_ratio_of_sums() -> None:
    result = _calculate(
        _slt_cdf(), _hourly("average({TTP} / ({NSP} * {RUNT}))", _slt_parameters())
    )

    # Every minute weighs the same: (30 * 0.8 + 30 * 0.4) / 60.
    assert result.datapoints[0].value == pytest.approx(0.6)


def test_per_bucket_guard_and_constants_outside_bucket_calls() -> None:
    cdf = _FakeCdf(
        {
            ("nsp", "1m"): _per_minute(
                _START, _END, lambda m: 0.0 if m < _START + timedelta(hours=1) else 10.0
            ),
            ("runt", "1m"): _per_minute(_START, _END, lambda _: 1.0),
            ("ttp", "1m"): _per_minute(_START, _END, lambda _: 8.0),
        }
    )

    result = _calculate(
        cdf,
        _hourly(
            "{SCALE} * sum({TTP}) / sum({NSP} * {RUNT})"
            " if sum({NSP} * {RUNT}) != 0 else {IDLE}",
            [
                *_slt_parameters(),
                ConstantParameter(alias="SCALE", value=100.0),
                ConstantParameter(alias="IDLE", value=-1.0),
            ],
        ),
    )

    assert _values(result) == [
        (_START, -1.0),
        (_START + timedelta(hours=1), 80.0),
    ]


def test_time_series_parameter_outside_bucket_calls_is_rejected() -> None:
    cdf = _slt_cdf()

    with pytest.raises(InvalidFormulaError, match="must be inside sum"):
        _calculate(cdf, _hourly("sum({TTP}) / {NSP}", _slt_parameters()))
    assert cdf.calls == []


def test_daily_buckets_follow_the_local_calendar_across_dst() -> None:
    # 2026-03-08 is 23 hours long in Denver.
    start = datetime(2026, 3, 8, 7, tzinfo=UTC)
    end = datetime(2026, 3, 10, 6, tzinfo=UTC)
    cdf = _FakeCdf({("runt", "1m"): _per_minute(start, end, lambda _: 1.0)})

    result = _calculate(
        cdf,
        CalculatorQuery(
            formula="sum({RUNT})",
            parameters=[_param("RUNT", "runt")],
            bucket_granularity="1d",
        ),
        start=start,
        end=end,
        timezone="America/Denver",
    )

    assert _values(result) == [
        (start, 23 * 60.0),
        (datetime(2026, 3, 9, 6, tzinfo=UTC), 24 * 60.0),
    ]
    assert {query.timezone for query in cdf.calls[0]} == {"America/Denver"}


def test_inputs_are_the_fetched_points_the_formula_ran_on() -> None:
    result = _calculate(_slt_cdf(), _hourly(_SLT, _slt_parameters()))

    assert len(result.datapoints) == 2
    assert {len(series) for series in result.inputs.values()} == {120}
    assert result.inputs["NSP"][0] == (_START, 10.0)


def test_plain_formula_ignores_bucket_granularity() -> None:
    cdf = _FakeCdf({("runt", "1h"): [(_START, 60.0)]})

    result = _calculate(
        cdf,
        CalculatorQuery(
            formula="{RUNT}",
            parameters=[_param("RUNT", "runt", "sum", "1h")],
            bucket_granularity="1d",
        ),
    )

    assert _values(result) == [(_START, 60.0)]
    assert [(q.start, q.end) for q in cdf.calls[0]] == [(_START, _END)]


# ---------------------------------------------------------------------------
# Missing points and fill_value
# ---------------------------------------------------------------------------


def _idle_first_ten_minutes(moment: datetime) -> float | None:
    return None if moment < _START + timedelta(minutes=10) else 8.0


def test_minute_without_throughput_is_dropped_by_default() -> None:
    result = _calculate(
        _slt_cdf(throughput=_idle_first_ten_minutes), _hourly(_SLT, _slt_parameters())
    )

    # 20 * 0.2 + 30 * 0.6: the ten running minutes without output are lost.
    assert result.datapoints[0].value == pytest.approx(22.0)


def test_fill_value_counts_a_minute_without_throughput_as_zero() -> None:
    result = _calculate(
        _slt_cdf(throughput=_idle_first_ten_minutes),
        _hourly(_SLT, _slt_parameters(fill_value=0.0)),
    )

    # 10 * (1 - 0) + 20 * 0.2 + 30 * 0.6.
    assert _values(result) == [
        (_START, 32.0),
        (_START + timedelta(hours=1), 24.0),
    ]
    assert result.inputs["TTP"][0].value == 0.0


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------


def test_bucket_and_plain_queries_retrieve_once_per_window() -> None:
    cdf = _slt_cdf()
    cdf.series[("runt", "1h")] = [(_START, 60.0), (_START + timedelta(hours=1), 60.0)]
    start = _START + timedelta(minutes=37)

    results = asyncio.run(
        Calculator(cdf.client).calculate_multiples(
            [
                CalculatorQuery(
                    formula="{RUNT}",
                    parameters=[_param("RUNT", "runt", "sum", "1h")],
                ),
                _hourly(_SLT, _slt_parameters()),
            ],
            start,
            _END,
        )
    )

    assert len(cdf.calls) == 2
    plain, bucketed = cdf.calls
    assert [(q.granularity, q.start) for q in plain] == [("1h", start)]
    assert {(q.granularity, q.start) for q in bucketed} == {("1m", _START)}
    assert _values(results[0]) == [(_START + timedelta(hours=1), 60.0)]
    assert _values(results[1]) == [
        (_START, 24.0),
        (_START + timedelta(hours=1), 24.0),
    ]


def test_bucket_queries_on_one_granularity_share_a_retrieve() -> None:
    cdf = _slt_cdf()

    results = asyncio.run(
        Calculator(cdf.client).calculate_multiples(
            [
                _hourly(_SLT, _slt_parameters()),
                _hourly("sum({TTP} / {NSP})", _slt_parameters()),
            ],
            _START,
            _END,
        )
    )

    assert len(cdf.calls) == 1
    assert len(cdf.calls[0]) == 3  # deduplicated across both queries
    assert [len(result.datapoints) for result in results] == [2, 2]


# ---------------------------------------------------------------------------
# Invalid queries fail before any retrieve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("formula", "parameters", "bucket_granularity", "match"),
    [
        ("sum({A})", [_param("A", "a")], None, "needs bucket_granularity"),
        (
            "sum({A})",
            [_param("A", "a")],
            "1fortnight",
            "unsupported bucket_granularity",
        ),
        (
            "sum({A} + {B})",
            [_param("A", "a", "sum", "1m"), _param("B", "b", "sum", "1d")],
            "1h",
            r"coarser than bucket_granularity '1h': B \(1d\)",
        ),
    ],
)
def test_invalid_bucket_granularity_raises_without_retrieving(
    formula: str,
    parameters: list[CalculatorParameter],
    bucket_granularity: str | None,
    match: str,
) -> None:
    cdf = _FakeCdf({})
    query = CalculatorQuery(
        formula=formula, parameters=parameters, bucket_granularity=bucket_granularity
    )

    with pytest.raises(BucketGranularityError, match=match):
        _calculate(cdf, query)
    assert cdf.calls == []


def test_bucket_query_with_only_constants_has_no_time_axis() -> None:
    cdf = _FakeCdf({})
    query = CalculatorQuery(
        formula="sum({K})",
        parameters=[ConstantParameter(alias="K", value=1.0)],
        bucket_granularity="1h",
    )

    with pytest.raises(MissingTimeAxisError):
        _calculate(cdf, query)
    assert cdf.calls == []
