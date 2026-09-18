from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from math import isnan
from unittest.mock import AsyncMock, MagicMock

import pytest
from cognite.client.data_classes.datapoints import Datapoints

from industrial_model.calculator import Calculator
from industrial_model.calculator.formula_expression.exceptions import (
    ParameterTimestampError,
)
from industrial_model.calculator.models import (
    CalculationResult,
    CalculatorQuery,
    ConstantParameter,
    TimeSeriesParameter,
)
from industrial_model.models import InstanceId

_START = datetime(2024, 1, 1, 7, 10, tzinfo=UTC)


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _param(
    alias: str,
    external_id: str,
    *,
    granularity: str | None = None,
) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space="s", external_id=external_id),
        aggregate_type="sum" if granularity is not None else None,
        granularity=granularity,
    )


def _aggregate_datapoints(
    external_id: str,
    values: list[float],
    timestamps: list[int],
) -> Datapoints:
    dp = Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type="numeric",
        external_id=external_id,
        instance_id=MagicMock(space="s", external_id=external_id),
        timestamp=timestamps,
    )
    dp.sum = values
    return dp


def _raw_datapoints(
    external_id: str,
    values: list[float],
    timestamps: list[int],
) -> Datapoints:
    return Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type="numeric",
        external_id=external_id,
        instance_id=MagicMock(space="s", external_id=external_id),
        timestamp=timestamps,
        value=values,
    )


def _client_returning(raw: list[Datapoints]) -> MagicMock:
    retrieve = AsyncMock(return_value=raw)
    client = MagicMock()
    client.time_series.data.retrieve = retrieve
    client.get_async_client.return_value = client
    return client


def _calculate(
    calc: Calculator,
    query: CalculatorQuery,
    start: datetime,
    end: datetime,
) -> CalculationResult:
    return asyncio.run(calc.calculate(query, start, end))


def _gq_gap_timestamps() -> list[int]:
    return [_ms(_START + timedelta(minutes=offset)) for offset in (0, 1, 2, 6, 7, 8)]


def test_calculate_rolling_average_fills_missing_minute_buckets() -> None:
    end = _START + timedelta(minutes=9)
    param = _param("GQ", "ts1", granularity="1m")
    raw = [
        _aggregate_datapoints(
            "ts1",
            [10.0, 20.0, 30.0, 100.0, 110.0, 120.0],
            _gq_gap_timestamps(),
        )
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(formula="rolling_average({GQ}, 3)", parameters=[param]),
        _START,
        end,
    )

    expected_minutes = [0, 1, 2, 3, 4, 6, 7, 8]
    assert [dp.timestamp for dp in result.datapoints] == [
        _START + timedelta(minutes=minute) for minute in expected_minutes
    ]
    assert [dp.value for dp in result.datapoints] == [
        10.0,
        15.0,
        20.0,
        25.0,
        30.0,
        100.0,
        105.0,
        110.0,
    ]
    gq = [dp.value for dp in result.inputs["GQ"]]
    assert gq[:3] == [10.0, 20.0, 30.0]
    assert isnan(gq[3]) and isnan(gq[4])
    assert gq[5:] == [100.0, 110.0, 120.0]
    assert [dp.timestamp for dp in result.inputs["GQ"]] == [
        dp.timestamp for dp in result.datapoints
    ]


def test_calculate_rolling_average_emits_trailing_partial_windows() -> None:
    end = _START + timedelta(minutes=12)
    param = _param("GQ", "ts1", granularity="1m")
    raw = [
        _aggregate_datapoints(
            "ts1",
            [10.0, 20.0, 30.0, 100.0, 110.0, 120.0],
            _gq_gap_timestamps(),
        )
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(formula="rolling_average({GQ}, 3)", parameters=[param]),
        _START,
        end,
    )

    by_minute = {dp.timestamp: dp.value for dp in result.datapoints}
    assert by_minute[_START + timedelta(minutes=6)] == 100.0
    assert by_minute[_START + timedelta(minutes=7)] == 105.0
    assert by_minute[_START + timedelta(minutes=8)] == 110.0
    assert by_minute[_START + timedelta(minutes=9)] == 115.0
    assert by_minute[_START + timedelta(minutes=10)] == 120.0
    assert _START + timedelta(minutes=11) not in by_minute


def test_calculate_rolling_average_without_granularity_stays_count_based() -> None:
    end = _START + timedelta(minutes=9)
    param = _param("A", "ts1")
    timestamps = _gq_gap_timestamps()
    raw = [
        _raw_datapoints(
            "ts1",
            [10.0, 20.0, 30.0, 100.0, 110.0, 120.0],
            timestamps,
        )
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(formula="rolling_average({A}, 3)", parameters=[param]),
        _START,
        end,
    )

    assert [dp.value for dp in result.datapoints] == [
        10.0,
        15.0,
        20.0,
        50.0,
        80.0,
        110.0,
    ]
    assert [dp.timestamp for dp in result.datapoints] == [
        _START + timedelta(minutes=offset) for offset in (0, 1, 2, 6, 7, 8)
    ]


def test_calculate_does_not_fill_gaps_without_rolling_average() -> None:
    end = _START + timedelta(minutes=3)
    p_a = _param("A", "ts_a", granularity="1m")
    p_b = _param("B", "ts_b", granularity="1m")
    raw = [
        _aggregate_datapoints(
            "ts_a",
            [10.0, 30.0],
            [_ms(_START), _ms(_START + timedelta(minutes=2))],
        ),
        _aggregate_datapoints(
            "ts_b",
            [1.0, 2.0, 3.0],
            [_ms(_START + timedelta(minutes=i)) for i in range(3)],
        ),
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(formula="{A} + {B}", parameters=[p_a, p_b]),
        _START,
        end,
    )

    assert [dp.timestamp for dp in result.datapoints] == [
        _START,
        _START + timedelta(minutes=2),
    ]
    assert [dp.value for dp in result.datapoints] == [11.0, 33.0]


def test_calculate_rolling_average_minus_constant_keeps_filled_minutes() -> None:
    end = _START + timedelta(minutes=6)
    gq = _param("GQ", "ts1", granularity="1m")
    offset = ConstantParameter(alias="C", value=5.0)
    raw = [
        _aggregate_datapoints(
            "ts1",
            [10.0, 20.0, 30.0],
            [_ms(_START + timedelta(minutes=i)) for i in range(3)],
        )
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(
            formula="rolling_average({GQ}, 3) - {C}",
            parameters=[gq, offset],
        ),
        _START,
        end,
    )

    by_minute = {dp.timestamp: dp.value for dp in result.datapoints}
    assert by_minute[_START] == 5.0
    assert by_minute[_START + timedelta(minutes=1)] == 10.0
    assert by_minute[_START + timedelta(minutes=2)] == 15.0
    assert by_minute[_START + timedelta(minutes=3)] == 20.0
    assert by_minute[_START + timedelta(minutes=4)] == 25.0
    assert _START + timedelta(minutes=5) not in by_minute


def test_calculate_rolling_average_mixed_granularity_stays_count_based() -> None:
    end = _START + timedelta(minutes=9)
    p_a = _param("A", "ts_a", granularity="1m")
    p_b = _param("B", "ts_b", granularity="5m")
    timestamps = _gq_gap_timestamps()
    raw = [
        _aggregate_datapoints(
            "ts_a",
            [10.0, 20.0, 30.0, 100.0, 110.0, 120.0],
            timestamps,
        ),
        _aggregate_datapoints(
            "ts_b",
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            timestamps,
        ),
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(
            formula="rolling_average({A}, 3) - {B}",
            parameters=[p_a, p_b],
        ),
        _START,
        end,
    )

    assert [dp.value for dp in result.datapoints] == [
        10.0,
        15.0,
        20.0,
        50.0,
        80.0,
        110.0,
    ]


def test_calculate_rolling_average_uses_overlapping_pre_start_bucket() -> None:
    start = _START + timedelta(seconds=30)
    end = _START + timedelta(minutes=3)
    param = _param("GQ", "ts1", granularity="1m")
    raw = [
        _aggregate_datapoints(
            "ts1",
            [10.0, 20.0, 30.0],
            [_ms(_START + timedelta(minutes=offset)) for offset in range(3)],
        )
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(formula="rolling_average({GQ}, 3)", parameters=[param]),
        start,
        end,
    )

    assert [dp.timestamp for dp in result.datapoints] == [
        _START + timedelta(minutes=offset) for offset in range(3)
    ]
    assert [dp.value for dp in result.datapoints] == [10.0, 15.0, 20.0]


def test_calculate_rolling_average_strict_raises_on_mismatched_buckets() -> None:
    end = _START + timedelta(minutes=3)
    p_a = _param("A", "ts_a", granularity="1m")
    p_b = _param("B", "ts_b", granularity="1m")
    raw = [
        _aggregate_datapoints(
            "ts_a",
            [10.0, 20.0, 30.0],
            [_ms(_START + timedelta(minutes=offset)) for offset in range(3)],
        ),
        _aggregate_datapoints(
            "ts_b",
            [1.0, 3.0],
            [_ms(_START), _ms(_START + timedelta(minutes=2))],
        ),
    ]

    with pytest.raises(ParameterTimestampError, match="timestamp mismatch"):
        _calculate(
            Calculator(_client_returning(raw)),
            CalculatorQuery(
                formula="rolling_average({A}, 3) - {B}",
                parameters=[p_a, p_b],
                alignment="strict",
            ),
            _START,
            end,
        )


def test_calculate_rolling_average_strict_fills_when_timestamps_match() -> None:
    end = _START + timedelta(minutes=4)
    p_a = _param("A", "ts_a", granularity="1m")
    p_b = _param("B", "ts_b", granularity="1m")
    timestamps = [_ms(_START + timedelta(minutes=offset)) for offset in range(3)]
    raw = [
        _aggregate_datapoints("ts_a", [10.0, 20.0, 30.0], timestamps),
        _aggregate_datapoints("ts_b", [1.0, 2.0, 3.0], timestamps),
    ]

    result = _calculate(
        Calculator(_client_returning(raw)),
        CalculatorQuery(
            formula="rolling_average({A}, 3) - {B}",
            parameters=[p_a, p_b],
            alignment="strict",
        ),
        _START,
        end,
    )

    assert [dp.value for dp in result.datapoints] == [9.0, 13.0, 17.0]
    assert [dp.timestamp for dp in result.datapoints] == [
        _START + timedelta(minutes=offset) for offset in range(3)
    ]
