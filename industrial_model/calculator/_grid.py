from __future__ import annotations

import ast
import calendar
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, tzinfo

from ._timezone import as_tzinfo, to_utc
from .formula_expression._compiler import compile_formula
from .models import Series, TimeSeriesParameterBase

# Longer unit names first so ``1mo`` is not parsed as ``1m``.
_GRANULARITY_RE = re.compile(
    r"^(\d+)"
    r"(months|month|mo|minutes|minute|mins|min|"
    r"seconds|second|secs|sec|"
    r"hours|hour|hrs|hr|"
    r"days|day|"
    r"weeks|week|wks|wk|"
    r"s|m|h|d|w)$",
    re.IGNORECASE,
)

_UNIT_ALIASES = {
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "m": "m",
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


def expand_series_on_grid(series: Series, grid: list[datetime]) -> Series:
    values = {_timestamp_ms(timestamp): value for timestamp, value in series}
    return [
        (timestamp, values.get(_timestamp_ms(timestamp), math.nan))
        for timestamp in grid
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
        shifted = _shift_months(local, delta)
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
