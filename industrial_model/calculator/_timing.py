from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext

# Exclusive stages reported in the DEBUG summary, in pipeline order.
_SUMMARY_STAGES = (
    "build_requests",
    "retrieve",
    "parse",
    "reduce",
    "align",
    "evaluate",
    "assemble",
)

_NOOP: AbstractContextManager[None] = nullcontext()


class StageTimer:
    """Accumulates exclusive wall-clock durations for named stages."""

    def __init__(self) -> None:
        self.durations: dict[str, float] = {}
        self.unique_timeseries = 0
        self._started_at = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.durations[name] = self.durations.get(name, 0.0) + (
                time.perf_counter() - started
            )

    def elapsed(self) -> float:
        return time.perf_counter() - self._started_at

    def format_summary(self, queries: int, *, ok: bool = True) -> str:
        total = self.elapsed()
        parts = [
            f"calculate finished in {total:.3f}s",
            f"status={'ok' if ok else 'error'}",
            f"queries={queries}",
            f"unique_timeseries={self.unique_timeseries}",
        ]
        summary = {name: self.durations.get(name, 0.0) for name in _SUMMARY_STAGES}
        for name in _SUMMARY_STAGES:
            duration = summary[name]
            pct = (100.0 * duration / total) if total else 0.0
            parts.append(f"{name}={duration:.3f}s ({pct:.1f}%)")
        bottleneck = max(summary, key=summary.__getitem__)
        parts.append(f"bottleneck={bottleneck} ({summary[bottleneck]:.3f}s)")
        return " ".join(parts)


def timed(timer: StageTimer | None, name: str) -> AbstractContextManager[None]:
    if timer is None:
        return _NOOP
    return timer.stage(name)
