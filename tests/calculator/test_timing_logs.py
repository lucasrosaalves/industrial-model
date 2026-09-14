from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from cognite.client.data_classes.datapoints import Datapoints

from industrial_model.calculator import Calculator, CalculatorQuery, TimeSeriesParameter
from industrial_model.calculator._timing import StageTimer
from industrial_model.models import InstanceId

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 1, 2, tzinfo=UTC)

_SUMMARY_STAGES = (
    "build_requests",
    "retrieve",
    "parse",
    "reduce",
    "align",
    "evaluate",
    "assemble",
)


def _param(alias: str, external_id: str) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space="s", external_id=external_id),
    )


def _datapoints(external_id: str, values: list[float]) -> Datapoints:
    base = int(_START.timestamp() * 1000)
    return Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type="numeric",
        external_id=external_id,
        instance_id=MagicMock(space="s", external_id=external_id),
        timestamp=[base + i * 60_000 for i in range(len(values))],
        value=values,
    )


def _client_returning(raw: list[Datapoints]) -> MagicMock:
    retrieve = AsyncMock(return_value=raw)
    client = MagicMock()
    client.time_series.data.retrieve = retrieve
    client.get_async_client.return_value = client
    return client


def _run_simple_calculate(client: MagicMock) -> None:
    asyncio.run(
        Calculator(client).calculate(
            CalculatorQuery(formula="{A} * 2", parameters=[_param("A", "ts1")]),
            _START,
            _END,
        )
    )


def test_debug_logs_are_silent_by_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="industrial_model.calculator")
    raw = [_datapoints("ts1", [1.0, 2.0, 3.0])]
    _run_simple_calculate(_client_returning(raw))

    assert "bottleneck=" not in caplog.text
    assert "calculate finished" not in caplog.text


def test_debug_logs_stage_summary_and_query_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="industrial_model.calculator")
    raw = [_datapoints("ts1", [1.0, 2.0, 3.0])]
    _run_simple_calculate(_client_returning(raw))

    assert "calculate finished" in caplog.text
    assert "status=ok" in caplog.text
    assert "queries=1" in caplog.text
    assert "unique_timeseries=1" in caplog.text
    assert "cdf_chunks=1" in caplog.text
    for stage in _SUMMARY_STAGES:
        assert f"{stage}=" in caplog.text
    assert "bottleneck=" in caplog.text
    assert "retrieve chunk 1/1: 1 series" in caplog.text
    assert "query formula={A} * 2" in caplog.text
    assert "aligned_points=3" in caplog.text
    summary_records = [
        record.message
        for record in caplog.records
        if "calculate finished" in record.message
    ]
    assert len(summary_records) == 1
    assert "\n" not in summary_records[0]


def test_debug_logs_shared_retrieve_across_queries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="industrial_model.calculator")
    raw = [_datapoints("ts1", [1.0, 2.0])]
    calc = Calculator(_client_returning(raw))
    param = _param("A", "ts1")

    asyncio.run(
        calc.calculate_multiples(
            [
                CalculatorQuery(formula="{A} + 1", parameters=[param]),
                CalculatorQuery(formula="{A} * 2", parameters=[param]),
            ],
            _START,
            _END,
        )
    )

    assert "queries=2" in caplog.text
    assert "status=ok" in caplog.text
    assert "unique_timeseries=1" in caplog.text
    assert caplog.text.count("retrieve chunk") == 1
    assert "formula={A} + 1" in caplog.text
    assert "formula={A} * 2" in caplog.text


def test_debug_logs_summary_when_calculate_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="industrial_model.calculator")
    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(side_effect=RuntimeError("cdf down"))
    client.get_async_client.return_value = client

    with pytest.raises(RuntimeError, match="cdf down"):
        _run_simple_calculate(client)

    assert "status=error" in caplog.text
    assert "calculate finished" in caplog.text
    assert "build_requests=" in caplog.text
    assert "retrieve=" in caplog.text
    assert "bottleneck=" in caplog.text


def test_format_summary_names_longest_exclusive_stage() -> None:
    timer = StageTimer()
    timer._started_at = time.perf_counter() - 2.0
    timer.durations["retrieve"] = 1.6
    timer.durations["evaluate"] = 0.2
    timer.durations["build_requests"] = 9.0
    timer.unique_timeseries = 12
    timer.cdf_chunks = 1

    text = timer.format_summary(queries=3)

    assert "\n" not in text
    assert "status=ok" in text
    assert "queries=3" in text
    assert "unique_timeseries=12" in text
    assert "cdf_chunks=1" in text
    assert "build_requests=9.000s" in text
    assert "bottleneck=build_requests (9.000s)" in text


def test_format_summary_marks_error_status() -> None:
    text = StageTimer().format_summary(queries=1, ok=False)

    assert "status=error" in text
    assert "\n" not in text
