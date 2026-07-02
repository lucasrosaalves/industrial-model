from __future__ import annotations

import ast

import pytest

from industrial_model.calculator.formula_expression._compiler import compile_formula
from industrial_model.calculator.formula_expression.exceptions import (
    InvalidFormulaError,
)


def test_compiler_cache_reuses_compiled_formula_instances() -> None:
    compile_formula.cache_clear()

    first = compile_formula("{A} + {B}")
    second = compile_formula("{A} + {B}")

    assert first is second
    assert compile_formula.cache_info().hits == 1


def test_compiler_cache_miss_for_different_formulas() -> None:
    compile_formula.cache_clear()

    first = compile_formula("{A} + {B}")
    second = compile_formula("{A} - {B}")

    assert first is not second
    assert compile_formula.cache_info().misses == 2


def test_compiler_preserves_variable_order_without_duplicates() -> None:
    compiled = compile_formula("{B} + {A} + {B}")

    assert compiled.variables == ("B", "A")


def test_compiler_rewrites_placeholders_to_internal_names() -> None:
    compiled = compile_formula("{APV} - {FPV}")

    assert (
        compiled.expression
        == "__formula_expression_param_0 - __formula_expression_param_1"
    )
    assert compiled.name_map == {
        "APV": "__formula_expression_param_0",
        "FPV": "__formula_expression_param_1",
    }


def test_compiler_stores_normalized_raw_formula() -> None:
    compiled = compile_formula("\t{A}\n+\n{B} ")

    assert compiled.raw == "{A} + {B}"


def test_compiler_stores_parsed_ast_tree() -> None:
    compiled = compile_formula("{A} + {B}")

    assert isinstance(compiled.tree, ast.Expression)
    assert isinstance(compiled.tree.body, ast.BinOp)


def test_compiler_assigns_unique_internal_names_for_many_parameters() -> None:
    compiled = compile_formula("{A} + {B} + {C} + {D}")

    assert compiled.name_map == {
        "A": "__formula_expression_param_0",
        "B": "__formula_expression_param_1",
        "C": "__formula_expression_param_2",
        "D": "__formula_expression_param_3",
    }


def test_compiler_supports_parameter_names_starting_with_underscore() -> None:
    compiled = compile_formula("{_A} + {B}")

    assert compiled.variables == ("_A", "B")
    assert "_A" in compiled.name_map


def test_compiler_supports_parameter_names_with_digits() -> None:
    compiled = compile_formula("{A1} + {B2}")

    assert compiled.variables == ("A1", "B2")


def test_compile_formula_rejects_empty_string() -> None:
    with pytest.raises(InvalidFormulaError, match="must not be empty"):
        compile_formula("")


def test_compile_formula_rejects_non_string_input() -> None:
    with pytest.raises(TypeError, match="formula must be a string"):
        compile_formula(123)  # type: ignore[arg-type]


def test_compile_formula_rejects_formula_without_parameters() -> None:
    with pytest.raises(InvalidFormulaError, match="at least one parameter"):
        compile_formula("1 + 2")


def test_compile_formula_rejects_invalid_placeholder_syntax() -> None:
    with pytest.raises(InvalidFormulaError, match="invalid placeholder syntax"):
        compile_formula("{{A}}")
