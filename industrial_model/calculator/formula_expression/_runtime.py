from __future__ import annotations

from collections.abc import Mapping, Sequence

from ._compiler import CompiledFormula
from ._evaluator import evaluate_tree
from ._types import EvaluationResult, ParameterValue
from .exceptions import MissingParameterError, ParameterError, ParameterLengthError


def evaluate_compiled(
    formula: CompiledFormula,
    parameters: Mapping[str, ParameterValue],
) -> EvaluationResult:
    missing = [name for name in formula.variables if name not in parameters]
    if missing:
        raise MissingParameterError(missing)

    normalized: dict[str, tuple[float, ...]] = {}
    lengths_by_name: dict[str, int] = {}
    for original_name, safe_name in formula.name_map.items():
        series = _normalize_parameter(original_name, parameters[original_name])
        normalized[safe_name] = series
        lengths_by_name[original_name] = len(series)

    if len(set(lengths_by_name.values())) != 1:
        raise ParameterLengthError(lengths_by_name)

    length = next(iter(lengths_by_name.values()))
    if length == 0:
        # Every referenced parameter resolved to an empty series, so there is
        # nothing to compute over: return an empty result rather than erroring.
        return ()

    return evaluate_tree(formula.tree, normalized, length=length)


def _normalize_parameter(name: str, value: object) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ParameterError(f"parameter {name!r} must be a numeric sequence")

    normalized: list[float] = []
    append = normalized.append
    for item in value:
        # Fast path for the overwhelmingly common exact ``float``/``int`` cases,
        # falling back to ``isinstance`` only to preserve subclass acceptance
        # (while still rejecting ``bool``).
        item_type = type(item)
        if item_type is float:
            append(item)
        elif item_type is int:
            append(float(item))
        elif isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ParameterError(f"parameter {name!r} must be a numeric sequence")
        else:
            append(float(item))

    return tuple(normalized)
