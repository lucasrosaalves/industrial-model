from __future__ import annotations

from collections.abc import Mapping

from ._compiler import compile_formula
from ._runtime import evaluate_compiled
from ._types import EvaluationResult, ParameterValue


def evaluate(
    formula: str,
    parameters: Mapping[str, ParameterValue] | None = None,
    **kwargs: ParameterValue,
) -> EvaluationResult:
    """Evaluate a formula over aligned numeric parameter sequences.

    Structural problems (bad syntax, unknown identifiers, missing parameters,
    mismatched lengths, non-numeric values) raise a subclass of
    :class:`~formula_expression.exceptions.FormulaError`.

    When every referenced parameter is an empty sequence the result is an empty
    tuple ``()`` - there is nothing to compute over, so this is treated as a
    valid (empty) result rather than an error. A *mix* of empty and non-empty
    parameters is still a length mismatch and raises ``ParameterLengthError``.

    Arithmetic failures that depend on the parameter *values* are intentionally
    left as their native Python exceptions and are **not** wrapped in
    ``FormulaError``: dividing or taking a modulo by zero raises
    ``ZeroDivisionError`` and an overflowing exponentiation raises
    ``OverflowError`` (both subclasses of ``ArithmeticError``).

    Conditional expressions (``{A} / {B} if {B} != 0 else 0``), comparisons
    (``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``) and boolean operators
    (``and``, ``or``) are supported and are evaluated element-by-element: for
    each series element, only the selected branch is evaluated, so a
    division-by-zero (or other value-dependent failure) in the branch that is
    *not* selected for a given element never raises.
    """

    values = dict(parameters or {})
    values.update(kwargs)
    return evaluate_compiled(compile_formula(formula), values)
