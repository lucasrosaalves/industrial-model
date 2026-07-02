from __future__ import annotations

import time

import pytest

from industrial_model.calculator.formula_expression import evaluate
from tests.calculator.formula_expression._support import (
    REPRESENTATIVE_FORMULAS,
    assert_values_allclose,
    parameter_names_for,
    random_dataset,
    reference_evaluate,
)

COMPLEX_FORMULAS = [
    "(({APD} + {AED}) / {AVD}) - (({FPD} + {FED}) / {FVD})",
    "100 * ({AEKG}+{A0KG}+(({AELBS}+{A0LBS})*0.453592)) / "
    "({AEKG}+{A0KG}+{A1KG}+{R1KG}+{R2KG}+{R3KG}+"
    "(({AELBS}+{A0LBS}+{A1LBS}+{R1LBS}+{R2LBS}+{R3LBS})*0.453592))",
    "(200000 * ({CPPST1} + {CPPST2}+{EPPST1} + {EPPST2})) / {TWH}",
    "100*({SCP})/({FG}+{IP}+{SCP})",
    "({VMCM} - {FDCM} - {OFCM} - {PPCM} - {ECCM}) / {SVCM}",
    "(24*3600) - {LLOEE} - {ALOEE} - {PLOEE} - {QLOEE}",
    "{R1KG}+{R2KG}+{R3KG}+(({R1LBS}+{R2LBS}+{R3LBS})*0.453592)",
    "((({A} + {B}) * ({C} - {D})) / (({E} + 1) * ({F} + 1))) ** 2 + {G} % {H}",
]


@pytest.mark.parametrize("formula", COMPLEX_FORMULAS, ids=lambda f: f[:40])
def test_complex_formula_matches_reference_on_large_dataset(formula: str) -> None:
    names = sorted(parameter_names_for([formula]))
    parameters = random_dataset(names, length=10_000, seed=17)

    result = evaluate(formula, parameters)
    expected = reference_evaluate(formula, parameters)

    assert len(result) == 10_000
    assert_values_allclose(result, expected, rel=1e-9, abs=1e-9)


@pytest.mark.parametrize(
    "formula",
    REPRESENTATIVE_FORMULAS,
    ids=lambda f: f.strip().replace(" ", "")[:40],
)
def test_all_representative_formulas_match_reference_on_large_dataset(
    formula: str,
) -> None:
    names = sorted(parameter_names_for([formula]))
    parameters = random_dataset(names, length=2_000, seed=29)

    result = evaluate(formula, parameters)
    expected = reference_evaluate(formula, parameters)

    assert_values_allclose(result, expected, rel=1e-9, abs=1e-9)


def test_evaluates_100k_point_dataset_correctly() -> None:
    length = 100_000
    parameters = random_dataset(["A", "B", "C"], length=length, seed=3)

    result = evaluate("({A} + {B}) * {C} - {A}", parameters)

    assert len(result) == length
    expected = reference_evaluate("({A} + {B}) * {C} - {A}", parameters)
    assert_values_allclose(result, expected, rel=1e-9, abs=1e-9)


def test_evaluation_scales_to_large_dataset_within_time_budget() -> None:
    parameters = random_dataset(["A", "B", "C", "D", "E"], length=200_000, seed=5)
    formula = "({A} + {B}) * {C} - {D} / {E}"

    start = time.perf_counter()
    result = evaluate(formula, parameters)
    elapsed = time.perf_counter() - start

    assert len(result) == 200_000
    # Generous bound; pure-Python evaluation of 200k points stays well under this.
    assert elapsed < 10.0


def test_repeated_parameter_reuse_on_large_dataset() -> None:
    parameters = random_dataset(["A"], length=5_000, seed=11)
    formula = "{A} * {A} - {A} + ({A} / {A})"

    result = evaluate(formula, parameters)
    expected = reference_evaluate(formula, parameters)

    assert_values_allclose(result, expected, rel=1e-9, abs=1e-9)


def test_deeply_nested_formula_matches_reference() -> None:
    formula = "(((({A} + {B}) * {C}) - {D}) / {E}) + (({F} - {G}) * ({H} + {I}))"
    names = sorted(parameter_names_for([formula]))
    parameters = random_dataset(names, length=4_000, seed=23)

    result = evaluate(formula, parameters)
    expected = reference_evaluate(formula, parameters)

    assert_values_allclose(result, expected, rel=1e-9, abs=1e-9)


def test_evaluation_is_deterministic_across_runs() -> None:
    parameters = random_dataset(["A", "B"], length=3_000, seed=7)
    formula = "({A} * 2 + {B}) / 3"

    first = evaluate(formula, parameters)
    second = evaluate(formula, parameters)

    assert first == second


def test_addition_is_commutative_on_large_dataset() -> None:
    parameters = random_dataset(["A", "B"], length=5_000, seed=31)

    left = evaluate("{A} + {B}", parameters)
    right = evaluate("{B} + {A}", parameters)

    assert_values_allclose(left, right, rel=1e-12, abs=1e-12)


def test_multiplication_distributes_over_addition_on_large_dataset() -> None:
    parameters = random_dataset(["A", "B", "C"], length=5_000, seed=37)

    distributed = evaluate("{A} * ({B} + {C})", parameters)
    expanded = evaluate("{A} * {B} + {A} * {C}", parameters)

    assert_values_allclose(distributed, expanded, rel=1e-9, abs=1e-9)


def test_additive_identity_on_large_dataset() -> None:
    parameters = random_dataset(["A"], length=5_000, seed=41)

    result = evaluate("{A} + 0", parameters)

    assert_values_allclose(result, tuple(parameters["A"]), rel=1e-12, abs=1e-12)


def test_multiplicative_identity_on_large_dataset() -> None:
    parameters = random_dataset(["A"], length=5_000, seed=43)

    result = evaluate("{A} * 1", parameters)

    assert_values_allclose(result, tuple(parameters["A"]), rel=1e-12, abs=1e-12)


def test_self_subtraction_is_zero_on_large_dataset() -> None:
    parameters = random_dataset(["A"], length=5_000, seed=47)

    result = evaluate("{A} - {A}", parameters)

    assert all(value == 0.0 for value in result)


def test_self_division_is_one_on_large_dataset() -> None:
    parameters = random_dataset(["A"], length=5_000, seed=53)

    result = evaluate("{A} / {A}", parameters)

    assert_values_allclose(result, [1.0] * 5_000, rel=1e-12, abs=1e-12)
