from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import (
    CompiledFormula,
    compile_formula,
)
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
)


def test_compile_formula_is_exported_and_cached() -> None:
    first = compile_formula("{A} + {B}")

    assert isinstance(first, CompiledFormula)
    assert compile_formula("{A} + {B}") is first


def test_plain_formula_parameters_are_its_placeholders() -> None:
    compiled = compile_formula("({A} - {B}) / {A} if {A} != 0 else 0")

    assert compiled.parameters == ("A", "B")
    assert compiled.outer_parameters == ("A", "B")


def test_bucket_formula_parameters_include_aggregated_placeholders() -> None:
    compiled = compile_formula("sum({A} * {B}) / average({C}) * {K}")

    assert compiled.parameters == ("K", "A", "B", "C")
    assert compiled.outer_parameters == ("K",)


def test_bucket_keys_are_not_parameters() -> None:
    compiled = compile_formula("sum({A})")

    assert compiled.parameters == ("A",)
    assert compiled.outer_parameters == ()


def test_unknown_function_is_rejected_at_compile_time() -> None:
    with pytest.raises(InvalidFormulaError, match="unknown formula function: SUM"):
        compile_formula("SUM({A})")
