from __future__ import annotations

import industrial_model.calculator.formula_expression as formula_expression
from industrial_model.calculator.formula_expression import (
    CompiledFormula,
    compile_formula,
    evaluate,
)
from industrial_model.calculator.formula_expression._compiler import (
    CompiledFormula as _CompiledFormula,
)
from industrial_model.calculator.formula_expression._compiler import (
    compile_formula as _compile_formula,
)
from tests.calculator.formula_expression._support import assert_values_equal


def test_package_exports_evaluate_and_compile_formula() -> None:
    assert formula_expression.__all__ == [
        "CompiledFormula",
        "compile_formula",
        "evaluate",
    ]
    assert formula_expression.evaluate is evaluate
    # The public names are the engine's own compiler, not copies.
    assert compile_formula is _compile_formula
    assert CompiledFormula is _CompiledFormula


def test_private_helpers_are_not_exported_at_package_top_level() -> None:
    assert not hasattr(formula_expression, "Formula")
    assert not hasattr(formula_expression, "FormulaError")


def test_keyword_parameters_are_supported_for_simple_calls() -> None:
    result = evaluate(
        "{APV} - {FPV}",
        APV=[10.0, 20.0],
        FPV=[3.0, 5.0],
    )
    assert_values_equal(result, [7.0, 15.0])


def test_keyword_parameters_override_mapping_values() -> None:
    result = evaluate(
        "{APV} - {FPV}",
        {
            "APV": [10.0, 20.0],
            "FPV": [9.0, 9.0],
        },
        FPV=[3.0, 5.0],
    )
    assert_values_equal(result, [7.0, 15.0])


def test_evaluate_accepts_mapping_subclass() -> None:
    class ParameterMapping(dict[str, list[float]]):
        pass

    result = evaluate(
        "{A} + {B}",
        ParameterMapping({"A": [1.0, 2.0], "B": [3.0, 4.0]}),
    )
    assert_values_equal(result, [4.0, 6.0])


def test_evaluate_returns_new_tuple_each_call() -> None:
    first = evaluate("{A} + 1", {"A": [1.0]})
    second = evaluate("{A} + 1", {"A": [1.0]})
    assert first == second
    assert first is not second
