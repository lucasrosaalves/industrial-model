from __future__ import annotations

import math

import pytest

from industrial_model.calculator.formula_expression import evaluate
from tests.calculator.formula_expression._support import (
    assert_values_equal,
)


def test_single_parameter_passthrough() -> None:
    result = evaluate("{VALUE}", {"VALUE": [42.0, 99.0]})
    assert_values_equal(result, [42.0, 99.0])


def test_operator_precedence_without_parentheses() -> None:
    result = evaluate("{A} + {B} * {C}", {"A": [1.0], "B": [2.0], "C": [3.0]})
    assert_values_equal(result, [7.0])


def test_deeply_nested_parentheses() -> None:
    result = evaluate(
        "(({A} + ({B} * ({C} + 1))) / 2)",
        {"A": [2.0], "B": [3.0], "C": [4.0]},
    )
    assert_values_equal(result, [8.5])


def test_large_numeric_constants_from_production_formulas() -> None:
    result = evaluate(
        "(24*3600) - {LLOEE} - {ALOEE} - {PLOEE} - {QLOEE}",
        {
            "LLOEE": [100.0, 200.0],
            "ALOEE": [50.0, 75.0],
            "PLOEE": [25.0, 30.0],
            "QLOEE": [10.0, 15.0],
        },
    )
    assert_values_equal(result, [86215.0, 86080.0])


def test_scientific_notation_constant() -> None:
    result = evaluate("{A} * 1e-3", {"A": [1000.0, 2000.0]})
    assert_values_equal(result, [1.0, 2.0])


def test_accepts_tuple_parameters() -> None:
    result = evaluate("{A} + {B}", {"A": (1.0, 2.0), "B": (3.0, 4.0)})
    assert_values_equal(result, [4.0, 6.0])


def test_accepts_range_parameters() -> None:
    result = evaluate("{A} * 2", {"A": range(3)})
    assert_values_equal(result, [0.0, 2.0, 4.0])


def test_accepts_integer_values_in_sequences() -> None:
    result = evaluate("{A} + {B}", {"A": [1, 2, 3], "B": [4, 5, 6]})
    assert_values_equal(result, [5.0, 7.0, 9.0])


def test_single_element_sequence() -> None:
    result = evaluate("{A} / 4", {"A": [8.0]})
    assert_values_equal(result, [2.0])


def test_long_sequence_evaluation() -> None:
    length = 1000
    values = [float(index) for index in range(length)]
    result = evaluate("{A} + 1", {"A": values})
    assert len(result) == length
    assert result[0] == 1.0
    assert result[-1] == float(length - 1) + 1.0


def test_division_by_zero_raises_error() -> None:
    with pytest.raises(ZeroDivisionError):
        evaluate("{A} / {B}", {"A": [1.0, -2.0], "B": [0.0, 0.0]})


def test_modulo_by_zero_raises_error() -> None:
    # Value-dependent arithmetic failures are intentionally left as native
    # Python exceptions rather than wrapped in FormulaError.
    with pytest.raises(ZeroDivisionError):
        evaluate("{A} % {B}", {"A": [1.0], "B": [0.0]})


def test_exponentiation_overflow_raises_overflow_error() -> None:
    # Float exponentiation overflows quickly instead of building a huge int.
    with pytest.raises(OverflowError):
        evaluate("{A} ** 1000000000", {"A": [10.0]})


def test_constant_only_division_by_zero_is_preserved_at_runtime() -> None:
    # Constant folding skips subtrees that raise ArithmeticError so the runtime
    # error semantics of a constant-only ``1 / 0`` are preserved.
    with pytest.raises(ZeroDivisionError):
        evaluate("{A} + 1 / 0", {"A": [1.0]})


def test_nan_in_parameters_propagates() -> None:
    nan = float("nan")
    result = evaluate("{A} + {B}", {"A": [nan, 1.0], "B": [2.0, nan]})
    assert math.isnan(result[0])
    assert math.isnan(result[1])


def test_negative_parameter_values() -> None:
    result = evaluate("{A} - {B}", {"A": [-5.0, -1.0], "B": [-3.0, 2.0]})
    assert_values_equal(result, [-2.0, -3.0])


def test_zero_values() -> None:
    result = evaluate(
        "{A} * {B} + {C}", {"A": [0.0, 5.0], "B": [100.0, 0.0], "C": [1.0, 1.0]}
    )
    assert_values_equal(result, [1.0, 1.0])


def test_double_unary_negation() -> None:
    result = evaluate("-(-{A})", {"A": [3.0, -4.0]})
    assert_values_equal(result, [3.0, -4.0])


def test_modulo_with_floats() -> None:
    result = evaluate("{A} % {B}", {"A": [7.5, 10.0], "B": [2.0, 3.0]})
    assert_values_equal(result, [1.5, 1.0])


def test_power_with_zero_exponent() -> None:
    result = evaluate("{A} ** 0", {"A": [0.0, 5.0, -3.0]})
    assert_values_equal(result, [1.0, 1.0, 1.0])


def test_power_with_fractional_exponent() -> None:
    result = evaluate("{A} ** 0.5", {"A": [4.0, 9.0]})
    assert_values_equal(result, [2.0, 3.0])


def test_many_parameters_in_one_formula() -> None:
    parameters = {f"P{index}": [float(index)] for index in range(10)}
    formula = " + ".join(f"{{P{index}}}" for index in range(10))
    result = evaluate(formula, parameters)
    assert_values_equal(result, [45.0])


def test_parameter_name_with_underscore_and_digits() -> None:
    result = evaluate("{_A1}", {"_A1": [7.0, 8.0]})
    assert_values_equal(result, [7.0, 8.0])


def test_result_is_tuple_not_list() -> None:
    result = evaluate("{A} + 1", {"A": [1.0, 2.0]})
    assert isinstance(result, tuple)


@pytest.mark.parametrize(
    ("formula", "parameters", "expected"),
    [
        ("{A} + {B} / {C}", {"A": [10.0], "B": [6.0], "C": [3.0]}, [12.0]),
        ("({A} + {B}) / {C}", {"A": [10.0], "B": [6.0], "C": [4.0]}, [4.0]),
        ("-{A} * +{B}", {"A": [2.0], "B": [3.0]}, [-6.0]),
        ("{A} ** {B}", {"A": [2.0], "B": [3.0]}, [8.0]),
        ("100 * {A} / 10", {"A": [5.0]}, [50.0]),
    ],
)
def test_operator_precedence_and_forms(
    formula: str,
    parameters: dict[str, list[float]],
    expected: list[float],
) -> None:
    result = evaluate(formula, parameters)
    assert_values_equal(result, expected)
