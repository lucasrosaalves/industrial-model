from __future__ import annotations

from collections.abc import Sequence
from typing import TypeAlias

ParameterValue: TypeAlias = Sequence[float | int]
EvaluationResult: TypeAlias = tuple[float, ...]
