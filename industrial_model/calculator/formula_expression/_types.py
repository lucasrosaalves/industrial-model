from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypeAlias

ParameterValue: TypeAlias = Sequence[float | int]
EvaluationResult: TypeAlias = tuple[float, ...]
# Formula call that evaluates its argument per aligned point, then aggregates
# the results by the query's ``bucket_granularity`` (``sum({A} / {B})``). Only
# ``Calculator`` can evaluate it: it needs timestamps to bucket by.
BucketAggregate: TypeAlias = Literal["sum", "average"]
