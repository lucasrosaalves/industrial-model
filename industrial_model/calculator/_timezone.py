from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

# Used only to step hour+ rolling-average grids. Retrieve forwards ``timezone``
# to CDF as-is; IANA / UTC-offset rules are enforced there.
_OFFSET_RE = re.compile(
    r"^(?:UTC)?(?P<sign>[+-])(?P<hours>\d{1,2})"
    r"(?::(?P<colon_minutes>\d{2})|(?P<hhmm>\d{2}))?$",
    re.IGNORECASE,
)


def as_tzinfo(value: str | None) -> tzinfo:
    """Resolve an optional IANA id / UTC offset for local calendar stepping."""

    if value is None:
        return UTC
    offset = _parse_utc_offset(value)
    if offset is not None:
        return offset
    if value.upper() == "UTC":
        return UTC
    return ZoneInfo(value)


def to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _parse_utc_offset(value: str) -> timezone | None:
    match = _OFFSET_RE.fullmatch(value)
    if match is None:
        return None
    hours = int(match.group("hours"))
    minutes_token = match.group("colon_minutes") or match.group("hhmm")
    minutes = int(minutes_token) if minutes_token is not None else 0
    if hours > 18 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group("sign") == "-":
        delta = -delta
    return timezone(delta)
