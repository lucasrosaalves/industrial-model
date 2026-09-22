from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import isnan
from zoneinfo import ZoneInfo

import pytest

from industrial_model.calculator._grid import (
    build_bucket_grid,
    expand_series_on_grid,
    formula_uses_rolling_average,
    parse_granularity,
    shared_aggregate_granularity,
)
from industrial_model.calculator.models import TimeSeriesParameter
from industrial_model.models import InstanceId


def test_parse_granularity_accepts_short_and_long_units() -> None:
    assert parse_granularity("1m") == (1, "m")
    assert parse_granularity("15m") == (15, "m")
    assert parse_granularity("1mo") == (1, "mo")
    assert parse_granularity("2hours") == (2, "h")
    assert parse_granularity("1day") == (1, "d")
    assert parse_granularity("1q") == (1, "q")
    assert parse_granularity("2quarters") == (2, "q")
    assert parse_granularity("1y") == (1, "y")
    assert parse_granularity("3t") == (3, "m")


def test_parse_granularity_rejects_unknown() -> None:
    assert parse_granularity("1fortnight") is None
    assert parse_granularity("") is None


def test_build_grid_steps_quarters_and_years_by_calendar_months() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    quarters = build_bucket_grid(
        start, datetime(2025, 1, 1, tzinfo=UTC), "1q", None, [start]
    )
    assert quarters == [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 4, 1, tzinfo=UTC),
        datetime(2024, 7, 1, tzinfo=UTC),
        datetime(2024, 10, 1, tzinfo=UTC),
    ]
    years = build_bucket_grid(
        start, datetime(2027, 1, 1, tzinfo=UTC), "1y", None, [start]
    )
    assert years == [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    ]


def test_shared_aggregate_granularity_requires_a_uniform_aggregate() -> None:
    shared = TimeSeriesParameter(
        alias="A",
        timeseries_instance_id=InstanceId(space="s", external_id="a"),
        aggregate_type="sum",
        granularity="1m",
    )
    other = TimeSeriesParameter(
        alias="B",
        timeseries_instance_id=InstanceId(space="s", external_id="b"),
        aggregate_type="sum",
        granularity="5m",
    )
    raw = TimeSeriesParameter(
        alias="C",
        timeseries_instance_id=InstanceId(space="s", external_id="c"),
    )
    assert shared_aggregate_granularity([shared]) == "1m"
    assert shared_aggregate_granularity([shared, other]) is None
    assert shared_aggregate_granularity([shared, raw]) is None


def test_formula_uses_rolling_average_detects_nested_calls() -> None:
    assert formula_uses_rolling_average("rolling_average({A}, 3) - {B}")
    assert not formula_uses_rolling_average("{A} + {B}")


def test_build_minute_grid_fills_from_start_to_end() -> None:
    start = datetime(2024, 1, 1, 7, 10, tzinfo=UTC)
    end = start + timedelta(minutes=4)
    grid = build_bucket_grid(
        start,
        end,
        "1m",
        None,
        [start + timedelta(minutes=2)],
    )
    assert grid == [start + timedelta(minutes=offset) for offset in range(4)]


def test_build_minute_grid_keeps_overlapping_bucket_before_start() -> None:
    start = datetime(2024, 1, 1, 7, 10, 30, tzinfo=UTC)
    end = start + timedelta(minutes=3)
    bucket = datetime(2024, 1, 1, 7, 10, tzinfo=UTC)
    grid = build_bucket_grid(
        start,
        end,
        "1m",
        None,
        [bucket + timedelta(minutes=1)],
    )
    assert grid == [bucket + timedelta(minutes=offset) for offset in range(4)]


def test_build_minute_grid_drops_bucket_that_ends_at_start() -> None:
    start = datetime(2024, 1, 1, 7, 10, tzinfo=UTC)
    end = start + timedelta(minutes=2)
    earlier = start - timedelta(minutes=1)
    grid = build_bucket_grid(start, end, "1m", None, [earlier, start])
    assert grid == [start, start + timedelta(minutes=1)]


def test_build_daily_grid_follows_dst_in_local_timezone() -> None:
    start = datetime(2024, 3, 9, 5, 0, tzinfo=UTC)  # 00:00 EST
    end = datetime(2024, 3, 12, 4, 0, tzinfo=UTC)  # 00:00 EDT on the 12th
    grid = build_bucket_grid(
        start,
        end,
        "1d",
        "America/New_York",
        [start],
    )
    ny = ZoneInfo("America/New_York")
    assert [moment.astimezone(ny) for moment in grid] == [
        datetime(2024, 3, 9, tzinfo=ny),
        datetime(2024, 3, 10, tzinfo=ny),
        datetime(2024, 3, 11, tzinfo=ny),
    ]


def test_build_daily_grid_keeps_local_day_that_overlaps_start() -> None:
    start = datetime(2024, 3, 9, 17, 0, tzinfo=UTC)  # 12:00 EST
    end = datetime(2024, 3, 12, 4, 0, tzinfo=UTC)  # 00:00 EDT on the 12th
    midnight = datetime(2024, 3, 9, 5, 0, tzinfo=UTC)  # 00:00 EST
    grid = build_bucket_grid(
        start,
        end,
        "1d",
        "America/New_York",
        [midnight],
    )
    ny = ZoneInfo("America/New_York")
    assert [moment.astimezone(ny) for moment in grid] == [
        datetime(2024, 3, 9, tzinfo=ny),
        datetime(2024, 3, 10, tzinfo=ny),
        datetime(2024, 3, 11, tzinfo=ny),
    ]


def test_expand_series_on_grid_inserts_nan_for_missing_buckets() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    grid = [start, start + timedelta(minutes=1), start + timedelta(minutes=2)]
    filled = expand_series_on_grid([(start, 10.0), (grid[2], 30.0)], grid)
    assert filled[0] == (start, 10.0)
    assert filled[1][0] == grid[1] and isnan(filled[1][1])
    assert filled[2] == (grid[2], 30.0)


@pytest.mark.parametrize(
    "formula",
    ["{A}", "rolling_average({A}, 3)"],
)
def test_formula_uses_rolling_average_parametrized(formula: str) -> None:
    assert formula_uses_rolling_average(formula) is ("rolling_average" in formula)
