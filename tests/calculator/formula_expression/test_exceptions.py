from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression.exceptions import (
    FormulaError,
    InvalidFormulaError,
    MissingParameterError,
)


def test_missing_parameter_error_is_formula_error() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        evaluate("{A}", {})

    assert isinstance(exc_info.value, FormulaError)


def test_invalid_formula_error_is_formula_error() -> None:
    with pytest.raises(InvalidFormulaError) as exc_info:
        evaluate("{A} +")

    assert isinstance(exc_info.value, FormulaError)


def test_missing_parameter_error_exposes_missing_names() -> None:
    error = MissingParameterError(["B", "A", "C"])

    assert error.missing == ("B", "A", "C")
    assert str(error) == "missing formula parameter(s): B, A, C"


def test_missing_parameter_error_accepts_list_and_stores_tuple() -> None:
    error = MissingParameterError(["X"])

    assert error.missing == ("X",)


def test_missing_parameter_error_message_includes_parameter_name() -> None:
    with pytest.raises(MissingParameterError, match="HEADCOUNT"):
        evaluate("{APV}/{HEADCOUNT}", {"APV": [1.0]})
