from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
    MissingParameterError,
    ParameterError,
)


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os').system('echo unsafe')",
        "{A}.__class__",
        "{A}[0]",
        "'text'",
        "{A",
        "{A B}",
        "{A} // 2",
        "[{A}]",
        "lambda x: x",
        "eval('1')",
        "{A}({B})",
        "{A} + {B}; {A}",
        "for x in {A}: x",
        "{A} += 1",
        "{A} | {B}",
        "{A} & {B}",
        "{A} ^ {B}",
        "{A} << 1",
        "{A} >> 1",
        "~{A}",
        "not {A}",
        "{A} is {B}",
        "{A} in {B}",
        "f'{A}'",
        "{A}: {B}",
        "{A} + ...",
        "... + {A}",
        "{A} + None",
        "{A} + {B}.real",
        "({A}) for {B} in {C}",
    ],
)
def test_rejects_unsafe_or_unsupported_formula_syntax(formula: str) -> None:
    with pytest.raises(InvalidFormulaError):
        evaluate(formula)


@pytest.mark.parametrize(
    "formula",
    [
        "{}",
        "{{A}}",
        "{A}{B}",
        "{123}",
        "{A + B}",
        "{A-B}",
        "{A.B}",
        "{A@B}",
    ],
)
def test_rejects_invalid_placeholder_syntax(formula: str) -> None:
    with pytest.raises(InvalidFormulaError):
        evaluate(formula)


def test_rejects_invalid_formula_syntax_with_message() -> None:
    with pytest.raises(InvalidFormulaError, match="invalid formula syntax"):
        evaluate("{A} +* {B}")


def test_rejects_unresolved_braces_after_replacement() -> None:
    with pytest.raises(InvalidFormulaError, match="invalid placeholder syntax"):
        evaluate("{{A}}")


@pytest.mark.parametrize("formula", ["{A} + True", "{A} + False", "{A} + None"])
def test_rejects_non_numeric_constants(formula: str) -> None:
    with pytest.raises(InvalidFormulaError, match="numeric constants"):
        evaluate(formula, {"A": [1.0, 2.0]})


def test_rejects_formula_without_parameters() -> None:
    with pytest.raises(InvalidFormulaError, match="at least one parameter"):
        evaluate("1 + 2 * 3")


def test_rejects_constant_only_expression_with_no_placeholders() -> None:
    with pytest.raises(InvalidFormulaError, match="at least one parameter"):
        evaluate("42")


def test_rejects_whitespace_only_formula() -> None:
    with pytest.raises(InvalidFormulaError, match="must not be empty"):
        evaluate("   ")


@pytest.mark.parametrize(
    "value",
    [
        ["x", "y"],
        [True, False],
        [1.0, None],
        [1.0, "2"],
    ],
)
def test_rejects_non_numeric_sequences(value: list[object]) -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": value})  # type: ignore[dict-item]


@pytest.mark.parametrize("value", [object(), "1", True, 3.14, {"A": 1}])
def test_rejects_invalid_parameter_values(value: object) -> None:
    with pytest.raises(ParameterError, match="numeric sequence"):
        evaluate("{A} + 1", {"A": value})  # type: ignore[dict-item]


def test_rejects_non_string_formula() -> None:
    with pytest.raises(TypeError, match="formula must be a string"):
        evaluate(123)  # type: ignore[arg-type]


def test_raises_for_single_missing_parameter() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        evaluate("{A} + {B}", {"A": [1.0, 2.0]})

    assert exc_info.value.missing == ("B",)
    assert str(exc_info.value) == "missing formula parameter(s): B"


def test_raises_for_all_missing_parameters_in_formula_order() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        evaluate("{B} + {A} + {B}")

    assert exc_info.value.missing == ("B", "A")


def test_raises_for_missing_parameter_when_extra_parameters_provided() -> None:
    with pytest.raises(MissingParameterError) as exc_info:
        evaluate("{A} + {B}", {"A": [1.0], "C": [2.0]})

    assert exc_info.value.missing == ("B",)


def test_rejects_unknown_identifier_outside_placeholder() -> None:
    with pytest.raises(InvalidFormulaError, match="unknown formula identifier"):
        evaluate("{A} + B")
