from datetime import datetime


def datetime_to_ms_iso_timestamp(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        raise ValueError(f"Expected datetime object, got {type(dt)}")
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="milliseconds")
