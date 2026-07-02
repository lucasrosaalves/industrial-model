from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression.exceptions import (
    FormulaError,
    ParameterError,
    ParameterLengthError,
)


def test_all_empty_parameter_sequences_return_empty_result() -> None:
    assert evaluate("{A} + 1", {"A": []}) == ()


def test_all_empty_multi_parameter_sequences_return_empty_result() -> None:
    assert evaluate("{A} + {B}", {"A": [], "B": []}) == ()


def test_mixed_empty_and_non_empty_parameters_raise_length_error() -> None:
    with pytest.raises(ParameterLengthError, match="length mismatch"):
        evaluate("{A} + {B}", {"A": [], "B": [1.0]})


def test_rejects_bytes_parameter_values() -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": b"\x01\x02"})


def test_rejects_string_parameter_values() -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": "12"})  # type: ignore[dict-item]


def test_rejects_none_parameter_value() -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": None})  # type: ignore[dict-item]


def test_rejects_dict_parameter_value() -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": {"x": 1.0}})  # type: ignore[dict-item]


def test_rejects_nested_sequence_parameter_value() -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": [[1.0, 2.0]]})  # type: ignore[list-item]


def test_rejects_mismatched_lengths_with_three_parameters() -> None:
    with pytest.raises(ParameterLengthError, match="length mismatch"):
        evaluate(
            "{A} + {B} + {C}",
            {"A": [1.0, 2.0], "B": [1.0, 2.0, 3.0], "C": [1.0, 2.0]},
        )


def test_length_mismatch_error_reports_names_and_lengths() -> None:
    with pytest.raises(ParameterLengthError) as exc_info:
        evaluate("{A} + {B}", {"A": [1.0, 2.0], "B": [1.0, 2.0, 3.0]})

    assert exc_info.value.lengths == {"A": 2, "B": 3}
    assert "'A' has 2" in str(exc_info.value)
    assert "'B' has 3" in str(exc_info.value)


def test_length_mismatch_ignores_unused_parameters() -> None:
    result = evaluate(
        "{A} + 1",
        {"A": [1.0, 2.0], "UNUSED": [1.0, 2.0, 3.0, 4.0]},
    )
    assert result == (2.0, 3.0)


def test_parameter_errors_are_formula_errors() -> None:
    assert issubclass(ParameterError, FormulaError)
    assert issubclass(ParameterLengthError, ParameterError)


def test_parameter_error_message_includes_parameter_name() -> None:
    with pytest.raises(ParameterError, match="parameter 'A'"):
        evaluate("{A} + 1", {"A": [1.0, "x"]})  # type: ignore[list-item]


def test_evaluate_with_kwargs_only() -> None:
    result = evaluate("{A} + {B}", A=[1.0, 2.0], B=[3.0, 4.0])
    assert result == (4.0, 6.0)


def test_evaluate_with_empty_mapping_and_kwargs() -> None:
    result = evaluate("{X} * 2", {}, X=[5.0])
    assert result == (10.0,)


def test_evaluate_with_none_parameters_and_kwargs() -> None:
    result = evaluate("{X} + 1", None, X=[2.0])
    assert result == (3.0,)
