from collections.abc import Callable
from datetime import datetime
from typing import (
    ParamSpec,
    TypeVar,
)

from anyio import to_thread

T_Retval = TypeVar("T_Retval")
P = ParamSpec("P")


def datetime_to_ms_iso_timestamp(dt: datetime) -> str:
    if not isinstance(dt, datetime):
        raise ValueError(f"Expected datetime object, got {type(dt)}")
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="milliseconds")


async def run_async(
    func: Callable[..., T_Retval],
    *args: object,
    cancellable: bool = False,
) -> T_Retval:
    return await to_thread.run_sync(func, *args, cancellable=cancellable)
