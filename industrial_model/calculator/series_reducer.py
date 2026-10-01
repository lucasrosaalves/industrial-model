from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
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


def _share_timestamps(prepared: list[Series]) -> bool:
    first = prepared[0]
    return all(
        len(leaf) == len(first)
        and all(a[0] == b[0] for a, b in zip(leaf, first, strict=True))
        for leaf in prepared[1:]
    )


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


def _reduce_sum_filled(series: list[Series], fill_value: float) -> Series:
    """Sum several series on the union of their timestamps without a full grid.

    A missing point counts as ``fill_value``, including series that are empty
    (they never have a point). Empty input series still count toward how many
    fills apply at each timestamp. One pass over datapoints instead of
    materializing ``len(axis) × len(series)`` rows.
    """
    prepared = [_prepare(list(leaf)) for leaf in series if leaf]
    if not prepared:
        return []

    n_series = len(series)
    totals: defaultdict[datetime, float] = defaultdict(float)
    present: defaultdict[datetime, int] = defaultdict(int)
    for leaf in prepared:
        for ts, value in leaf:
            totals[ts] += value
            present[ts] += 1
    if not totals:
        return []
    if fill_value == 0.0:
        return sorted(totals.items(), key=lambda point: point[0])
    return [
        (ts, totals[ts] + fill_value * (n_series - present[ts]))
        for ts in sorted(totals)
    ]


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
        fill_value: float | None = None,
    ) -> Series:
        """Combine several series into one on their common timestamps.

        With ``fill_value``, combine on the union of their timestamps
        instead: a series without a point at a timestamp counts as
        ``fill_value`` there (``0`` for a count summed across lines).
        """
        if not series:
            return []
        if len(series) == 1:
            return _prepare(list(series[0]))
        if fill_value is not None:
            if reducer == "sum":
                return _reduce_sum_filled(series, fill_value)
            filled = self.align_filled(series, [fill_value] * len(series))
            return [
                (ts, _reduce_values(tuple(leaf[i][1] for leaf in filled), reducer))
                for i, (ts, _) in enumerate(filled[0])
            ]
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

    def align_filled(
        self,
        series: list[Series],
        fill_values: Sequence[float | None],
    ) -> list[Series]:
        """Align on the union of timestamps, filling where a value is given.

        A timestamp is kept when every series without a fill value has a
        point there; a series with a fill value uses it where it has none.
        When every series has a fill value, the axis is the union of all
        their timestamps.
        """
        if len(fill_values) != len(series):
            raise ValueError(
                f"got {len(fill_values)} fill value(s) for {len(series)} series"
            )
        if not series:
            return []

        prepared = [_prepare(list(leaf)) for leaf in series]
        if _share_timestamps(prepared):
            # Nothing to fill: the usual case for series on one minute grid.
            return prepared

        by_timestamp = [dict(leaf) for leaf in prepared]
        required = [index for index, fill in enumerate(fill_values) if fill is None]
        if required:
            first = min(required, key=lambda index: len(by_timestamp[index]))
            axis = sorted(by_timestamp[first])
        else:
            axis = sorted(set().union(*by_timestamp))

        aligned: list[Series] = [[] for _ in series]
        for ts in axis:
            if any(ts not in by_timestamp[index] for index in required):
                continue
            for j, values in enumerate(by_timestamp):
                value = values.get(ts)
                if value is None:
                    value = fill_values[j]
                    assert value is not None
                aligned[j].append((ts, value))
        return aligned
