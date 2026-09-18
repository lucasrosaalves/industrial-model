from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


def rolling_average(values: tuple[float, ...], window: int) -> tuple[float, ...]:
    """Simple moving average over the last ``window`` points (partial prefix).

    At index ``i`` the result is the mean of the finite values in
    ``values[max(0, i-window+1):i+1]``. ``NaN`` entries are skipped so a
    time-grid with missing buckets still averages the points that exist.
    An all-``NaN`` window yields ``NaN``. The output is always the same
    length as ``values``. ``window`` is assumed to be a positive integer
    (enforced at compile time).
    """

    length = len(values)
    if length == 0:
        return ()

    cumulative = [0.0] * (length + 1)
    counts = [0] * (length + 1)
    for index, value in enumerate(values):
        if math.isnan(value):
            cumulative[index + 1] = cumulative[index]
            counts[index + 1] = counts[index]
        else:
            cumulative[index + 1] = cumulative[index] + value
            counts[index + 1] = counts[index] + 1

    result: list[float] = []
    append = result.append
    for index in range(length):
        start = max(0, index - window + 1)
        count = counts[index + 1] - counts[start]
        if count == 0:
            append(math.nan)
        else:
            append((cumulative[index + 1] - cumulative[start]) / count)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class FunctionSpec:
    arity: int
    window_arg: int | None
    apply: Callable[[tuple[float, ...], int], tuple[float, ...]]


ALLOWED_FUNCTIONS: dict[str, FunctionSpec] = {
    "rolling_average": FunctionSpec(
        arity=2,
        window_arg=1,
        apply=rolling_average,
    ),
}
