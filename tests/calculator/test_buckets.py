"""Bucket spans and bucket aggregation for ``sum(...)`` / ``average(...)``.

Expected bucket starts were read from CDF (bdx-dev, 2026-09-30) with native
``count`` aggregates over a start that falls mid-bucket.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import nan
from zoneinfo import ZoneInfo

import pytest

from industrial_model.calculator._grid import (
    aggregate_into_buckets,
    bucket_span,
    min_granularity_seconds,
)

_DENVER = "America/Denver"
_MID = datetime(2026, 4, 15, 13, 37, 42, tzinfo=UTC)  # a Wednesday


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _minutes(
    start: datetime, count: int, value: float = 1.0
) -> list[tuple[datetime, float]]:
    return [(start + timedelta(minutes=i), value) for i in range(count)]


# ---------------------------------------------------------------------------
# bucket_span: where CDF starts the first bucket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("granularity", "timezone", "origin"),
    [
        # Sub-hour floors to the unit in UTC; the timezone is ignored.
        ("1m", None, _utc(2026, 4, 15, 13, 37)),
        ("15m", _DENVER, _utc(2026, 4, 15, 13, 37)),
        # The unit, not the multiple: 2h from 13:37 starts at 13:00.
        ("2h", None, _utc(2026, 4, 15, 13)),
        ("2h", _DENVER, _utc(2026, 4, 15, 13)),
        # Hour floors on the local clock of a half-hour offset.
        ("1h", "UTC+05:30", _utc(2026, 4, 15, 13, 30)),
        ("1d", None, _utc(2026, 4, 15)),
        ("1d", _DENVER, _utc(2026, 4, 15, 6)),
        # Weeks start at that day's local midnight, not on a Monday.
        ("7d", _DENVER, _utc(2026, 4, 15, 6)),
        ("1w", _DENVER, _utc(2026, 4, 15, 6)),
        ("1mo", _DENVER, _utc(2026, 4, 1, 6)),
    ],
)
def test_bucket_span_floors_start_to_the_unit(
    granularity: str, timezone: str | None, origin: datetime
) -> None:
    start, _ = bucket_span(_MID, _MID + timedelta(days=200), granularity, timezone)

    assert start == origin


@pytest.mark.parametrize("granularity", ["3mo", "1q", "2mo", "12mo", "1y"])
def test_bucket_span_floors_quarters_and_years_to_the_month(granularity: str) -> None:
    # CDF does not snap to a calendar quarter or year.
    mid_may = _utc(2026, 5, 20, 13, 37)

    start, _ = bucket_span(mid_may, mid_may + timedelta(days=1), granularity, _DENVER)

    assert start == _utc(2026, 5, 1, 6)


def test_bucket_span_returns_the_last_bucket_whole() -> None:
    start, stop = bucket_span(
        _utc(2026, 4, 15, 6), _utc(2026, 4, 16, 18), "1d", _DENVER
    )

    assert (start, stop) == (_utc(2026, 4, 15, 6), _utc(2026, 4, 17, 6))


def test_bucket_span_on_a_bucket_boundary_adds_nothing() -> None:
    start, stop = bucket_span(_utc(2026, 4, 15, 6), _utc(2026, 4, 17, 6), "1d", _DENVER)

    assert (start, stop) == (_utc(2026, 4, 15, 6), _utc(2026, 4, 17, 6))


def test_bucket_span_steps_months_on_the_local_calendar() -> None:
    _, stop = bucket_span(_utc(2026, 1, 20), _utc(2026, 3, 2), "1mo", _DENVER)

    # Midnight 1 March is still MST (UTC-7); DST starts on 8 March.
    assert stop == _utc(2026, 4, 1, 6)


def test_bucket_span_empty_window_is_empty() -> None:
    # Mid-bucket, so a naive "round end up" would return a whole day.
    start, stop = bucket_span(_utc(2026, 4, 15, 6), _utc(2026, 4, 15, 6), "1d", None)

    assert start == stop == _utc(2026, 4, 15)


def test_bucket_span_rejects_unknown_granularity() -> None:
    with pytest.raises(ValueError, match="unsupported granularity"):
        bucket_span(_MID, _MID, "1fortnight", None)


# ---------------------------------------------------------------------------
# aggregate_into_buckets
# ---------------------------------------------------------------------------


def test_aggregate_into_buckets_sums_minutes_per_hour() -> None:
    origin = _utc(2026, 4, 15, 13)
    series = _minutes(origin, 150, 2.0)  # 2.5 hours

    result = aggregate_into_buckets(series, origin, "1h", None, "sum")

    assert result == [
        (_utc(2026, 4, 15, 13), 120.0),
        (_utc(2026, 4, 15, 14), 120.0),
        (_utc(2026, 4, 15, 15), 60.0),
    ]


def test_aggregate_into_buckets_average_is_a_mean_of_present_points() -> None:
    origin = _utc(2026, 4, 15, 13)
    series = [(origin, 1.0), (origin + timedelta(minutes=5), 3.0)]

    result = aggregate_into_buckets(series, origin, "1h", None, "average")

    assert result == [(origin, 2.0)]


def test_aggregate_into_buckets_omits_empty_buckets_and_skips_nan() -> None:
    origin = _utc(2026, 4, 15)
    series = [
        (origin, 1.0),
        (origin + timedelta(hours=2), nan),
        (origin + timedelta(hours=3), 5.0),
        (origin + timedelta(hours=3, minutes=1), nan),
    ]

    result = aggregate_into_buckets(series, origin, "1h", None, "sum")

    assert result == [(origin, 1.0), (origin + timedelta(hours=3), 5.0)]


def test_aggregate_into_buckets_empty_series_is_empty() -> None:
    assert aggregate_into_buckets([], _utc(2026, 1, 1), "1d", None, "sum") == []


def test_aggregate_into_buckets_daily_follows_a_short_dst_day() -> None:
    # 2026-03-08 in Denver is 23 hours long.
    origin = _utc(2026, 3, 8, 7)
    series = _minutes(origin, 24 * 60)

    result = aggregate_into_buckets(series, origin, "1d", _DENVER, "sum")

    assert result == [(_utc(2026, 3, 8, 7), 23 * 60.0), (_utc(2026, 3, 9, 6), 60.0)]


def test_aggregate_into_buckets_hourly_keeps_the_repeated_fall_back_hour() -> None:
    # 2026-11-01 in Denver is 25 hours long: 01:00 happens twice.
    denver = ZoneInfo(_DENVER)
    origin = datetime(2026, 11, 1, tzinfo=denver).astimezone(UTC)
    series = _minutes(origin, 25 * 60)

    result = aggregate_into_buckets(series, origin, "1h", _DENVER, "sum")

    assert len(result) == 25
    assert all(value == 60.0 for _, value in result)


def test_aggregate_into_buckets_weekly_from_a_wednesday() -> None:
    origin = _utc(2026, 4, 15, 6)
    series = [
        (origin, 1.0),
        (_utc(2026, 4, 22, 5, 59), 2.0),
        (_utc(2026, 4, 22, 6), 4.0),
    ]

    result = aggregate_into_buckets(series, origin, "7d", _DENVER, "sum")

    assert result == [(origin, 3.0), (_utc(2026, 4, 22, 6), 4.0)]


# ---------------------------------------------------------------------------
# min_granularity_seconds
# ---------------------------------------------------------------------------


def test_min_granularity_seconds_orders_units() -> None:
    assert min_granularity_seconds("1m") == 60
    assert min_granularity_seconds("2h") == 7_200
    seconds = [min_granularity_seconds(g) for g in ("1d", "7d", "1mo", "3mo", "12mo")]
    known = [value for value in seconds if value is not None]
    assert known == sorted(known) and len(known) == len(seconds)


def test_min_granularity_seconds_unknown_is_none() -> None:
    assert min_granularity_seconds("1fortnight") is None
