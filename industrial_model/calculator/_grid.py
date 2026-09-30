from __future__ import annotations

import ast
import calendar
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, tzinfo

from ._timezone import as_tzinfo, to_utc
from .formula_expression._compiler import compile_formula
from .formula_expression._types import BucketAggregate
from .models import Series, TimeSeriesParameterBase

# Longer unit names first so ``1mo`` is not parsed as ``1m``.
_GRANULARITY_RE = re.compile(
    r"^(\d+)"
    r"(months|month|mo|minutes|minute|mins|min|"
    r"seconds|second|secs|sec|"
    r"quarters|quarter|"
    r"years|year|"
    r"hours|hour|hrs|hr|"
    r"days|day|"
    r"weeks|week|wks|wk|"
    r"s|m|h|d|w|q|y|t)$",
    re.IGNORECASE,
)

# Normalized units: s, m, h, d, w, mo, q, y. Same spellings the Cognite SDK
# accepts (``t`` is its alias for minutes).
_UNIT_ALIASES = {
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "m": "m",
    "t": "m",
    "min": "m",
    "mins": "m",
    "minute": "m",
    "minutes": "m",
    "h": "h",
    "hr": "h",
    "hrs": "h",
    "hour": "h",
    "hours": "h",
    "d": "d",
    "day": "d",
    "days": "d",
    "w": "w",
    "wk": "w",
    "wks": "w",
    "week": "w",
    "weeks": "w",
    "mo": "mo",
    "month": "mo",
    "months": "mo",
    "q": "q",
    "quarter": "q",
    "quarters": "q",
    "y": "y",
    "year": "y",
    "years": "y",
}

# Units whose buckets follow the calendar rather than a fixed length.
CALENDAR_UNITS = frozenset({"mo", "q", "y"})
_MONTHS_PER_UNIT = {"mo": 1, "q": 3, "y": 12}

# Shortest length of one unit, to compare granularities (``1m`` < ``1d``).
_MIN_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3_600,
    "d": 86_400,
    "w": 7 * 86_400,
    "mo": 28 * 86_400,
    "q": 89 * 86_400,
    "y": 365 * 86_400,
}


def formula_uses_rolling_average(formula: str) -> bool:
    compiled = compile_formula(formula)
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "rolling_average"
        for node in ast.walk(compiled.tree)
    )


def shared_aggregate_granularity(
    parameters: Sequence[TimeSeriesParameterBase],
) -> str | None:
    """Return the common CDF granularity, or ``None`` if it is not uniform.

    Raw parameters (no aggregate / no granularity) and mixed granularities
    disable grid fill so ``rolling_average`` stays count-based.
    """

    granularities: list[str] = []
    for parameter in parameters:
        if parameter.aggregate_type is None or parameter.granularity is None:
            return None
        granularities.append(parameter.granularity)
    if not granularities:
        return None
    first = granularities[0]
    if any(granularity != first for granularity in granularities[1:]):
        return None
    return first


def parse_granularity(granularity: str) -> tuple[int, str] | None:
    match = _GRANULARITY_RE.fullmatch(granularity.strip())
    if match is None:
        return None
    quantity = int(match.group(1))
    if quantity < 1:
        return None
    return quantity, _UNIT_ALIASES[match.group(2).lower()]


def build_bucket_grid(
    start: datetime,
    end: datetime,
    granularity: str,
    timezone: str | None,
    references: Sequence[datetime],
) -> list[datetime]:
    """Bucket starts that overlap ``[start, end)`` on ``granularity``.

    Phased from retrieved timestamps. A CDF aggregate whose bucket start is
    before ``start`` is kept when that bucket still overlaps the window.
    Sub-hour steps are fixed UTC durations (CDF ignores timezone for those).
    Hour and longer steps follow the local calendar of ``timezone`` (UTC if
    omitted) so DST days and month lengths stay correct.
    """

    parsed = parse_granularity(granularity)
    if parsed is None or not references:
        return []
    start_utc = to_utc(start)
    end_utc = to_utc(end)
    if end_utc <= start_utc:
        return []

    quantity, unit = parsed
    tz = as_tzinfo(timezone)
    ref = min(to_utc(moment) for moment in references)

    origin = ref
    while True:
        previous = _step(origin, quantity, unit, tz, -1)
        if previous >= origin:
            break
        if previous >= start_utc:
            origin = previous
            continue
        if origin > start_utc:
            origin = previous
        break

    grid: list[datetime] = []
    moment = origin
    while moment < end_utc:
        nxt = _step(moment, quantity, unit, tz, 1)
        if nxt <= moment:
            break
        if nxt > start_utc:
            grid.append(moment)
        moment = nxt
    return grid


def expand_series_on_grid(
    series: Series, grid: list[datetime], fill: float | None = None
) -> Series:
    """Place ``series`` on ``grid``; a bucket without a point gets ``fill``.

    Without a fill value the bucket is ``NaN``.
    """
    missing = math.nan if fill is None else fill
    values = {_timestamp_ms(timestamp): value for timestamp, value in series}
    return [
        (timestamp, values.get(_timestamp_ms(timestamp), missing)) for timestamp in grid
    ]


def _timestamp_ms(moment: datetime) -> int:
    return int(to_utc(moment).timestamp() * 1000)


def _step(
    moment: datetime, quantity: int, unit: str, tz: tzinfo, sign: int
) -> datetime:
    delta = quantity * sign
    if unit == "s":
        return moment + timedelta(seconds=delta)
    if unit == "m":
        return moment + timedelta(minutes=delta)
    local = moment.astimezone(tz)
    if unit == "h":
        shifted = _shift_wall(local, hours=delta)
    elif unit == "d":
        shifted = _shift_wall(local, days=delta)
    elif unit == "w":
        shifted = _shift_wall(local, days=7 * delta)
    else:
        shifted = _shift_months(local, delta * _MONTHS_PER_UNIT[unit])
    return shifted.astimezone(UTC)


def _shift_wall(local: datetime, *, hours: int = 0, days: int = 0) -> datetime:
    naive = local.replace(tzinfo=None) + timedelta(hours=hours, days=days)
    return _localize(naive, local.tzinfo)


def _shift_months(local: datetime, months: int) -> datetime:
    month_index = local.month - 1 + months
    year = local.year + month_index // 12
    month = month_index % 12 + 1
    day = min(local.day, calendar.monthrange(year, month)[1])
    naive = local.replace(tzinfo=None, year=year, month=month, day=day)
    return _localize(naive, local.tzinfo)


def _localize(naive: datetime, tz: tzinfo | None) -> datetime:
    if tz is None:
        return naive.replace(tzinfo=UTC)
    return naive.replace(tzinfo=tz)


def min_granularity_seconds(granularity: str) -> int | None:
    """Shortest possible bucket length, or ``None`` for an unknown granularity."""

    parsed = parse_granularity(granularity)
    if parsed is None:
        return None
    quantity, unit = parsed
    return quantity * _MIN_UNIT_SECONDS[unit]


def bucket_span(
    start: datetime,
    end: datetime,
    granularity: str,
    timezone: str | None,
) -> tuple[datetime, datetime]:
    """The whole buckets CDF aggregates over for ``[start, end)``, as UTC.

    CDF floors ``start`` to the granularity's *unit*, not its multiple:
    ``2h`` from 13:37 starts at 13:00, ``7d`` and ``1w`` at that day's local
    midnight (not a Monday), ``3mo`` / ``1q`` / ``1y`` at the 1st of that
    local month. The last bucket that starts before ``end`` is returned
    whole. Every bucket holds all of its data, including data outside
    ``[start, end)``. An empty window spans nothing.
    """

    quantity, unit = _require_granularity(granularity)
    tz = as_tzinfo(timezone)
    start_utc = to_utc(start)
    end_utc = to_utc(end)
    origin = _floor_to_unit(start_utc, unit, tz)
    if end_utc <= start_utc:
        return origin, origin
    stop = origin
    while stop < end_utc:
        stop = _next_bucket(stop, quantity, unit, tz)
    return origin, stop


def aggregate_into_buckets(
    series: Series,
    origin: datetime,
    granularity: str,
    timezone: str | None,
    aggregate: BucketAggregate,
) -> Series:
    """Aggregate an ascending series into buckets that start at ``origin``.

    ``origin`` comes from :func:`bucket_span`, so bucket starts match the
    timestamps CDF returns for the same granularity and timezone. ``NaN``
    values are skipped; a bucket with no value is omitted, as CDF omits
    empty buckets.
    """

    quantity, unit = _require_granularity(granularity)
    tz = as_tzinfo(timezone)
    result: Series = []
    bucket_start = to_utc(origin)
    bucket_end = _next_bucket(bucket_start, quantity, unit, tz)
    values: list[float] = []
    for timestamp, value in series:
        moment = to_utc(timestamp)
        if moment < bucket_start:
            continue
        while moment >= bucket_end:
            if values:
                result.append((bucket_start, _aggregate(values, aggregate)))
                values = []
            bucket_start = bucket_end
            bucket_end = _next_bucket(bucket_start, quantity, unit, tz)
        if not math.isnan(value):
            values.append(value)
    if values:
        result.append((bucket_start, _aggregate(values, aggregate)))
    return result


def _aggregate(values: list[float], aggregate: BucketAggregate) -> float:
    total = math.fsum(values)
    if aggregate == "sum":
        return total
    return total / len(values)


def _require_granularity(granularity: str) -> tuple[int, str]:
    parsed = parse_granularity(granularity)
    if parsed is None:
        raise ValueError(f"unsupported granularity: {granularity!r}")
    return parsed


def _floor_to_unit(moment: datetime, unit: str, tz: tzinfo) -> datetime:
    """Start of the unit containing ``moment`` (UTC in, UTC out).

    Sub-hour units floor in UTC (CDF ignores the timezone for them); hour
    and longer floor on the local calendar of ``tz``.
    """

    if unit == "s":
        return moment.replace(microsecond=0)
    if unit == "m":
        return moment.replace(second=0, microsecond=0)
    local = moment.astimezone(tz)
    if unit == "h":
        floored = local.replace(minute=0, second=0, microsecond=0)
    elif unit in ("d", "w"):
        floored = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        floored = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return floored.astimezone(UTC)


def _next_bucket(moment: datetime, quantity: int, unit: str, tz: tzinfo) -> datetime:
    """Start of the bucket after the one starting at ``moment`` (UTC).

    Hours are fixed durations, so a DST fall-back day has 25 hourly
    buckets. Days and longer follow the local wall clock (23/25 h days).
    """

    if unit == "s":
        return moment + timedelta(seconds=quantity)
    if unit == "m":
        return moment + timedelta(minutes=quantity)
    if unit == "h":
        return moment + timedelta(hours=quantity)
    local = moment.astimezone(tz)
    if unit == "d":
        shifted = _shift_wall(local, days=quantity)
    elif unit == "w":
        shifted = _shift_wall(local, days=7 * quantity)
    else:
        shifted = _shift_months(local, quantity * _MONTHS_PER_UNIT[unit])
    return shifted.astimezone(UTC)
