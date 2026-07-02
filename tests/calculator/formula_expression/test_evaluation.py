from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression.exceptions import (
    ParameterLengthError,
)
from tests.calculator.formula_expression._support import assert_values_equal


@pytest.mark.parametrize(
    ("formula", "a_values", "b_values", "expected_values"),
    [
        ("{A} + {B} * 2", [1.0, 2.0], [3.0, 4.0], [7.0, 10.0]),
        ("({A} + {B}) * 2", [1.0, 2.0], [3.0, 4.0], [8.0, 12.0]),
        ("-{A} + +{B}", [5.0, 6.0], [2.0, 10.0], [-3.0, 4.0]),
        ("{A} ** 3", [2.0, 3.0], [0.0, 0.0], [8.0, 27.0]),
        ("{A} % {B}", [7.0, 9.0], [4.0, 5.0], [3.0, 4.0]),
        ("\t{A}\n+\n{B} ", [2.0, 3.0], [4.0, 5.0], [6.0, 8.0]),
    ],
)
def test_evaluates_series_arithmetic(
    formula: str,
    a_values: list[float],
    b_values: list[float],
    expected_values: list[float],
) -> None:
    result = evaluate(formula, {"A": a_values, "B": b_values})
    assert_values_equal(result, expected_values)


def test_evaluates_representative_series_formula() -> None:
    parameters = {
        "APD": [10.0, 20.0, 30.0],
        "AED": [5.0, 10.0, 15.0],
        "AVD": [3.0, 5.0, 9.0],
        "FPD": [8.0, 10.0, 12.0],
        "FED": [2.0, 4.0, 6.0],
        "FVD": [5.0, 7.0, 9.0],
    }

    result = evaluate(
        "(({APD} + {AED}) / {AVD}) - (({FPD} + {FED}) / {FVD})",
        parameters,
    )

    assert_values_equal(result, [3.0, 4.0, 3.0])


def test_reuses_repeated_parameter_in_one_expression() -> None:
    result = evaluate("{A} + {A} * {A}", {"A": [3.0, 4.0, 5.0]})
    assert_values_equal(result, [12.0, 20.0, 30.0])


def test_ignores_unused_parameters() -> None:
    result = evaluate(
        "{A} + 1",
        {
            "A": [3.0, 4.0, 5.0],
            "UNUSED": [100.0, 100.0, 100.0],
        },
    )
    assert_values_equal(result, [4.0, 5.0, 6.0])


def test_uses_numeric_constants_with_series() -> None:
    result = evaluate("{APV}/10", {"APV": [10.0, 20.0, 30.0]})
    assert_values_equal(result, [1.0, 2.0, 3.0])


def test_rejects_mismatched_parameter_lengths() -> None:
    with pytest.raises(ParameterLengthError, match="length mismatch"):
        evaluate("{LEFT} + {RIGHT}", {"LEFT": [10.0, 20.0], "RIGHT": [1.0, 2.0, 3.0]})


def test_preserves_series_index_for_unit_conversion() -> None:
    result = evaluate(
        "{A1KG}+({A1LBS}*0.453592)",
        {"A1KG": [10.0, 20.0, 30.0], "A1LBS": [5.0, 5.0, 5.0]},
    )
    assert_values_equal(result, [12.26796, 22.26796, 32.26796])


def test_result_can_mix_multiple_series_and_numeric_constants() -> None:
    result = evaluate("({A} - {B}) / 2", {"A": [2.0, 4.0, 6.0], "B": [1.0, 2.0, 3.0]})
    assert_values_equal(result, [0.5, 1.0, 1.5])


def test_evaluates_formula_with_only_constants_and_one_parameter() -> None:
    result = evaluate("100 * {A} / 10", {"A": [5.0, 10.0]})
    assert_values_equal(result, [50.0, 100.0])


def test_evaluates_subtraction_chain() -> None:
    parms = {"A": [10.0, 20.0], "B": [1.0, 2.0], "C": [3.0, 4.0]}
    result = evaluate("{A} - {B} - {C}", parms)
    assert_values_equal(result, [6.0, 14.0])


def test_evaluates_division_chain() -> None:
    result = evaluate("{A} / {B} / {C}", {"A": [100.0], "B": [10.0], "C": [2.0]})
    assert_values_equal(result, [5.0])


def test_evaluates_mixed_scale_formula_like_production() -> None:
    result = evaluate(
        "(200000 * ({CPPST1} + {CPPST2})) / {CWH}",
        {"CPPST1": [1.0, 2.0], "CPPST2": [3.0, 4.0], "CWH": [10.0, 20.0]},
    )
    assert_values_equal(result, [80000.0, 60000.0])


def test_evaluates_percentage_style_formula() -> None:
    result = evaluate(
        "100*({SCP})/({FG}+{IP}+{SCP})",
        {"SCP": [10.0, 20.0], "FG": [30.0, 40.0], "IP": [10.0, 10.0]},
    )
    assert_values_equal(result, [20.0, 28.571428571428573])


@pytest.mark.parametrize(
    ("formula", "a_values", "b_values", "expected_values"),
    [
        ("{A} if {A} > {B} else {B}", [1.0, 5.0], [3.0, 2.0], [3.0, 5.0]),
        ("{A} == {B}", [1.0, 2.0], [1.0, 3.0], [1.0, 0.0]),
        ("{A} != {B}", [1.0, 2.0], [1.0, 3.0], [0.0, 1.0]),
        ("{A} >= {B}", [1.0, 2.0], [1.0, 3.0], [1.0, 0.0]),
        ("{A} <= {B}", [1.0, 2.0], [1.0, 3.0], [1.0, 1.0]),
        ("{A} > {B} and {A} < 10", [1.0, 20.0], [0.0, 5.0], [1.0, 0.0]),
        ("{A} > {B} or {A} < 0", [1.0, -5.0], [5.0, 0.0], [0.0, 1.0]),
        ("1 < {A} < 10", [0.0, 5.0, 20.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
    ],
)
def test_evaluates_conditional_and_comparison_formulas(
    formula: str,
    a_values: list[float],
    b_values: list[float],
    expected_values: list[float],
) -> None:
    result = evaluate(formula, {"A": a_values, "B": b_values})
    assert_values_equal(result, expected_values)


def test_nested_if_else_short_circuits_every_branch_independently() -> None:
    result = evaluate(
        "1/{A} if {A} != 0 else (1/{B} if {B} != 0 else 0)",
        {"A": [0.0, 2.0, 0.0], "B": [0.0, 100.0, 4.0]},
    )
    assert_values_equal(result, [0.0, 0.5, 0.25])
