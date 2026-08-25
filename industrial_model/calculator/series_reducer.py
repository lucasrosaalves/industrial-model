from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import assert_never

from .models import ReducerType, Series


def _prepare(leaf: Series) -> Series:
    """Return a time-ordered series; duplicate timestamps keep the last value."""
    if len(leaf) < 2:
        return list(leaf)

    sorted_ok = True
    has_duplicates = False
    prev = leaf[0][0]
    for i in range(1, len(leaf)):
        ts = leaf[i][0]
        if ts < prev:
            sorted_ok = False
            break
        if ts == prev:
            has_duplicates = True
        prev = ts

    if sorted_ok and not has_duplicates:
        return leaf

    ordered = leaf if sorted_ok else sorted(leaf, key=lambda point: point[0])
    collapsed: Series = [ordered[0]]
    for ts, value in ordered[1:]:
        if collapsed[-1][0] == ts:
            collapsed[-1] = (ts, value)
        else:
            collapsed.append((ts, value))
    return collapsed


def _iter_aligned_rows(
    prepared: list[Series],
) -> Iterator[tuple[datetime, tuple[float, ...]]]:
    k = len(prepared)
    lengths = [len(series) for series in prepared]
    idx = [0] * k

    while True:
        exhausted = False
        for j in range(k):
            if idx[j] >= lengths[j]:
                exhausted = True
                break
        if exhausted:
            break

        tmax = prepared[0][idx[0]][0]
        for j in range(1, k):
            ts = prepared[j][idx[j]][0]
            if ts > tmax:
                tmax = ts

        aligned = True
        for j in range(k):
            while idx[j] < lengths[j] and prepared[j][idx[j]][0] < tmax:
                idx[j] += 1
            if idx[j] >= lengths[j] or prepared[j][idx[j]][0] != tmax:
                aligned = False
                break

        if not aligned:
            continue

        yield tmax, tuple(prepared[j][idx[j]][1] for j in range(k))
        for j in range(k):
            idx[j] += 1


def _reduce_values(values: tuple[float, ...], reducer: ReducerType) -> float:
    match reducer:
        case "min":
            return min(values)
        case "max":
            return max(values)
        case "sum":
            return sum(values)
        case "average":
            return sum(values) / len(values)
        case _:
            assert_never(reducer)


class SeriesReducer:
    """Combines or aligns multiple timeseries by intersecting on timestamp.

    A timestamp survives only when every input series has a value for it.
    This is stricter than a positional zip: it tolerates series with gaps
    or misaligned points instead of silently pairing up unrelated values.

    Every input is normalized first (see :func:`_prepare`), including when a
    single series is passed, so the output does not depend on how many series
    the caller happened to supply.
    """

    def reduce(
        self,
        series: list[Series],
        reducer: ReducerType,
    ) -> Series:
        if not series:
            return []
        if len(series) == 1:
            return _prepare(list(series[0]))
        if any(not leaf for leaf in series):
            return []

        return [
            (ts, _reduce_values(values, reducer))
            for ts, values in _iter_aligned_rows([_prepare(leaf) for leaf in series])
        ]

    def align(self, series: list[Series]) -> list[Series]:
        """Filter each series to the timestamps present in every series."""
        if not series:
            return []
        if len(series) == 1:
            return [_prepare(list(series[0]))]
        if any(not leaf for leaf in series):
            return [[] for _ in series]

        aligned: list[Series] = [[] for _ in series]
        for ts, values in _iter_aligned_rows([_prepare(leaf) for leaf in series]):
            for j, value in enumerate(values):
                aligned[j].append((ts, value))
        return aligned
