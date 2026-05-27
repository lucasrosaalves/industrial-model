from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

try:
    from anyio.to_thread import run_sync as _run_sync
except ImportError:
    _run_sync = None  # type: ignore[assignment]

T_Retval = TypeVar("T_Retval")

_ASYNC_INSTALL_MSG = (
    "Async features require the optional async extra. "
    'Install it with: pip install "industrial-model[async]"'
)


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
    if _run_sync is None:
        raise RuntimeError(_ASYNC_INSTALL_MSG)

    return await _run_sync(func, *args, abandon_on_cancel=cancellable)
