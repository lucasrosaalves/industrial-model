from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
)
from tests.calculator.formula_expression._support import assert_values_equal


def test_rolling_average_uses_partial_windows_then_full_sma() -> None:
    result = evaluate(
        "rolling_average({A}, 3)",
        {"A": [10.0, 20.0, 30.0, 40.0]},
    )
    assert_values_equal(result, [10.0, 15.0, 20.0, 30.0])


def test_rolling_average_window_of_one_is_identity() -> None:
    result = evaluate("rolling_average({A}, 1)", {"A": [4.0, 8.0, 15.0]})
    assert_values_equal(result, [4.0, 8.0, 15.0])


def test_rolling_average_window_larger_than_series_is_expanding_mean() -> None:
    result = evaluate("rolling_average({A}, 5)", {"A": [2.0, 4.0, 6.0]})
    assert_values_equal(result, [2.0, 3.0, 4.0])


def test_rolling_average_empty_series_returns_empty_tuple() -> None:
    assert evaluate("rolling_average({A}, 3)", {"A": []}) == ()


def test_rolling_average_single_point_is_itself() -> None:
    result = evaluate("rolling_average({A}, 24)", {"A": [42.0]})
    assert_values_equal(result, [42.0])


def test_rolling_average_matches_independent_sma_on_mixed_values() -> None:
    values = [3.0, -1.0, 0.0, 8.5, -4.0, 2.0, 2.0, 10.0, -0.5, 1.5]
    window = 4
    result = evaluate("rolling_average({A}, 4)", {"A": values})
    expected = [
        sum(values[max(0, index - window + 1) : index + 1])
        / (index - max(0, index - window + 1) + 1)
        for index in range(len(values))
    ]
    assert len(result) == len(values)
    assert_values_equal(result, expected)


def test_unguarded_division_inside_rolling_average_still_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        evaluate(
            "rolling_average({A} / {B}, 2)",
            {"A": [10.0, 20.0], "B": [2.0, 0.0]},
        )


def test_rolling_average_composes_with_another_parameter() -> None:
    result = evaluate(
        "rolling_average({A}, 3) - {B}",
        {"A": [10.0, 20.0, 30.0, 40.0], "B": [1.0, 2.0, 3.0, 4.0]},
    )
    assert_values_equal(result, [9.0, 13.0, 17.0, 26.0])


def test_rolling_average_of_an_expression() -> None:
    result = evaluate(
        "rolling_average({A} + {B}, 2)",
        {"A": [1.0, 2.0, 3.0], "B": [10.0, 20.0, 30.0]},
    )
    assert_values_equal(result, [11.0, 16.5, 27.5])


def test_nested_rolling_average() -> None:
    result = evaluate(
        "rolling_average(rolling_average({A}, 2), 2)",
        {"A": [10.0, 20.0, 30.0, 40.0]},
    )
    assert_values_equal(result, [10.0, 12.5, 20.0, 30.0])


def test_rolling_average_of_guarded_division() -> None:
    result = evaluate(
        "rolling_average({A} / {B} if {B} != 0 else 0, 2)",
        {"A": [10.0, 20.0, 30.0, 40.0], "B": [2.0, 0.0, 5.0, 10.0]},
    )
    assert_values_equal(result, [5.0, 2.5, 3.0, 5.0])


def test_rolling_average_inside_ternary_uses_neighbors_for_the_window() -> None:
    result = evaluate(
        "rolling_average({A}, 2) if {B} > 0 else 0",
        {"A": [10.0, 20.0, 30.0], "B": [1.0, 0.0, 1.0]},
    )
    assert_values_equal(result, [10.0, 0.0, 25.0])


def test_nested_rolling_average_on_element_wise_path_matches_vectorized() -> None:
    result = evaluate(
        "rolling_average(rolling_average({A}, 2), 2) if {B} > 0 else 0",
        {"A": [10.0, 20.0, 30.0, 40.0], "B": [1.0, 1.0, 1.0, 1.0]},
    )
    assert_values_equal(result, [10.0, 12.5, 20.0, 30.0])


def test_rolling_average_stays_aligned_when_ternary_is_elsewhere() -> None:
    result = evaluate(
        "rolling_average({A}, 3) + ({B} if {B} > 0 else 0)",
        {"A": [10.0, 20.0, 30.0, 40.0], "B": [1.0, 0.0, 1.0, 1.0]},
    )
    assert_values_equal(result, [11.0, 15.0, 21.0, 31.0])


def test_rolling_average_does_not_run_when_the_call_is_never_selected() -> None:
    result = evaluate(
        "rolling_average({A} / {B}, 2) if {C} > 0 else 0",
        {"A": [10.0, 20.0], "B": [0.0, 0.0], "C": [0.0, 0.0]},
    )
    assert_values_equal(result, [0.0, 0.0])


def test_rolling_average_does_not_evaluate_indexes_outside_a_selected_window() -> None:
    result = evaluate(
        "rolling_average({A} / {B}, 2) if {C} > 0 else 0",
        {"A": [10.0, 20.0], "B": [5.0, 0.0], "C": [1.0, 0.0]},
    )
    assert_values_equal(result, [2.0, 0.0])


def test_outer_guard_does_not_protect_neighbors_inside_the_window() -> None:
    with pytest.raises(ZeroDivisionError):
        evaluate(
            "rolling_average({A} / {B}, 2) if {B} != 0 else 0",
            {"A": [10.0, 20.0, 30.0], "B": [2.0, 0.0, 5.0]},
        )


def test_rolling_average_accepts_folded_window_expression() -> None:
    result = evaluate("rolling_average({A}, 2 + 2)", {"A": [1.0, 2.0, 3.0, 4.0, 5.0]})
    assert_values_equal(result, [1.0, 1.5, 2.0, 2.5, 3.5])


def test_rolling_average_accepts_integral_float_window() -> None:
    result = evaluate("rolling_average({A}, 6 / 2)", {"A": [10.0, 20.0, 30.0, 40.0]})
    assert_values_equal(result, [10.0, 15.0, 20.0, 30.0])


def test_rolling_average_accepts_near_integer_folded_window() -> None:
    result = evaluate(
        "rolling_average({A}, 8.3 - 5.3)", {"A": [10.0, 20.0, 30.0, 40.0]}
    )
    assert_values_equal(result, [10.0, 15.0, 20.0, 30.0])


def test_rolling_average_of_scalar_is_that_scalar() -> None:
    result = evaluate("rolling_average(5, 3) + {A}", {"A": [1.0, 2.0, 3.0]})
    assert_values_equal(result, [6.0, 7.0, 8.0])


@pytest.mark.parametrize(
    ("formula", "match"),
    [
        ("foo({A})", "unknown formula function: foo"),
        ("rolling_average({A})", r"takes 2 arguments, got 1"),
        ("rolling_average({A}, 3, 4)", r"takes 2 arguments, got 3"),
        (
            "rolling_average({A}, window=3)",
            "does not accept keyword arguments",
        ),
        ("rolling_average(*{A}, 3)", "does not accept starred arguments"),
        ("rolling_average({A}, *3)", "does not accept starred arguments"),
        ("rolling_average({A}, {B})", "window must be a numeric constant"),
        ("rolling_average({A}, 0)", "window must be a positive integer"),
        ("rolling_average({A}, -1)", "window must be a positive integer"),
        ("rolling_average({A}, 1.5)", "window must be a positive integer"),
        ("{A} + rolling_average", "unknown formula identifier"),
    ],
)
def test_rolling_average_rejects_invalid_calls(formula: str, match: str) -> None:
    with pytest.raises(InvalidFormulaError, match=match):
        evaluate(formula, {"A": [1.0, 2.0], "B": [3.0, 4.0]})
