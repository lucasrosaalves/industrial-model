from __future__ import annotations

import ast

import pytest

from industrial_model.calculator.formula_expression import evaluate
from industrial_model.calculator.formula_expression._compiler import compile_formula
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
)


@pytest.mark.parametrize("aggregate", ["sum", "average"])
def test_bucket_call_becomes_a_per_point_term(aggregate: str) -> None:
    compiled = compile_formula(
        f"{aggregate}((({{NSP}} * {{RUNT}}) - {{TTP}}) / {{NSP}})"
    )

    [term] = compiled.bucket_terms
    assert term.aggregate == aggregate
    assert term.key == f"{aggregate}#0"
    assert term.formula.variables == ("NSP", "RUNT", "TTP")
    # The per-bucket formula only reads the term.
    assert compiled.variables == (term.key,)


def test_formula_without_bucket_calls_has_no_terms() -> None:
    assert compile_formula("{A} + {B}").bucket_terms == ()


def test_ratio_of_bucket_sums_has_one_term_per_call() -> None:
    compiled = compile_formula("sum({TTP}) / sum({NSP} * {RUNT})")

    first, second = compiled.bucket_terms
    assert first.formula.variables == ("TTP",)
    assert second.formula.variables == ("NSP", "RUNT")
    assert compiled.variables == (first.key, second.key)


def test_identical_bucket_calls_share_a_term() -> None:
    compiled = compile_formula("sum({A}) / sum({B}) if sum({B}) != 0 else 0")

    assert [term.formula.variables for term in compiled.bucket_terms] == [
        ("B",),
        ("A",),
    ]
    assert compiled.has_conditional


def test_same_argument_with_another_aggregate_is_another_term() -> None:
    compiled = compile_formula("sum({A}) - average({A})")

    assert [term.aggregate for term in compiled.bucket_terms] == ["sum", "average"]


def test_placeholders_outside_bucket_calls_stay_in_the_per_bucket_formula() -> None:
    compiled = compile_formula("100 * sum({A}) / {TARGET}")

    [term] = compiled.bucket_terms
    assert compiled.variables == ("TARGET", term.key)


def test_bucket_term_may_be_conditional() -> None:
    compiled = compile_formula("sum({A} / {B} if {B} != 0 else 0)")

    [term] = compiled.bucket_terms
    assert term.formula.has_conditional
    assert not compiled.has_conditional


def test_bucket_term_folds_constants() -> None:
    compiled = compile_formula("sum({A} * (24 * 3600))")

    body = compiled.bucket_terms[0].formula.tree.body
    assert isinstance(body, ast.BinOp)
    assert isinstance(body.right, ast.Constant)
    assert body.right.value == 86400


def test_bucket_calls_cannot_be_nested() -> None:
    with pytest.raises(InvalidFormulaError, match="cannot be nested"):
        compile_formula("sum(average({A}))")


def test_bucket_call_must_reference_a_parameter() -> None:
    with pytest.raises(
        InvalidFormulaError, match=r"sum\(\) must reference at least one parameter"
    ):
        compile_formula("sum(1) + {A}")


def test_bucket_call_takes_one_argument() -> None:
    with pytest.raises(InvalidFormulaError, match=r"sum\(\) takes 1 argument, got 2"):
        compile_formula("sum({A}, {B})")


def test_bucket_call_rejects_keyword_arguments() -> None:
    with pytest.raises(InvalidFormulaError, match="keyword arguments"):
        compile_formula("average({A}, window=2)")


def test_bucket_call_cannot_wrap_rolling_average_yet() -> None:
    with pytest.raises(
        InvalidFormulaError, match=r"sum\(\) cannot wrap rolling_average\(\) yet"
    ):
        compile_formula("sum(rolling_average({A}, 3))")


def test_rolling_average_cannot_be_combined_with_bucket_calls_yet() -> None:
    with pytest.raises(
        InvalidFormulaError,
        match=r"rolling_average\(\) cannot be combined with sum\(\) / average\(\)",
    ):
        compile_formula("rolling_average(sum({A}), 3)")


def test_bucket_call_name_is_case_sensitive() -> None:
    with pytest.raises(InvalidFormulaError, match="unknown formula function: SUM"):
        compile_formula("SUM({A})")


@pytest.mark.parametrize("formula", ["sum({A})", "sum({A}) / sum({B})"])
def test_evaluate_rejects_bucket_formulas(formula: str) -> None:
    with pytest.raises(InvalidFormulaError, match="evaluate the formula with Calc"):
        evaluate(formula, A=[1.0, 2.0], B=[1.0, 2.0])
