from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


def rolling_average(values: tuple[float, ...], window: int) -> tuple[float, ...]:
    """Simple moving average over the last ``window`` points (partial prefix).

    At index ``i`` the result is the mean of ``values[max(0, i-window+1):i+1]``.
    The output is always the same length as ``values``. ``window`` is assumed
    to be a positive integer (enforced at compile time).
    """

    length = len(values)
    if length == 0:
        return ()

    cumulative = [0.0] * (length + 1)
    for index, value in enumerate(values):
        cumulative[index + 1] = cumulative[index] + value

    result: list[float] = []
    append = result.append
    for index in range(length):
        start = max(0, index - window + 1)
        append((cumulative[index + 1] - cumulative[start]) / (index - start + 1))
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
