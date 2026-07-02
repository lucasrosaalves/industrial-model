from __future__ import annotations

import pytest

from industrial_model.calculator.formula_expression import evaluate
from tests.calculator.formula_expression._support import (
    REPRESENTATIVE_FORMULAS,
    assert_values_equal,
    parameter_names_for,
)


def formula_id(formula: str) -> str:
    return formula.strip().replace(" ", "")[:50]


def test_representative_fixture_contains_unique_formulas() -> None:
    assert len(REPRESENTATIVE_FORMULAS) == len(set(REPRESENTATIVE_FORMULAS))


def test_representative_fixture_contains_expected_parameters() -> None:
    parameter_names = parameter_names_for(REPRESENTATIVE_FORMULAS)

    assert {"APV", "HEADCOUNT", "A1KG", "A1LBS", "TDAI"} <= parameter_names


@pytest.mark.parametrize(
    "formula",
    REPRESENTATIVE_FORMULAS,
    ids=formula_id,
)
def test_evaluates_all_representative_formulas_without_error(
    formula: str,
    representative_parameters: dict[str, list[float]],
) -> None:
    result = evaluate(formula, representative_parameters)

    assert isinstance(result, tuple)
    assert len(result) == 2


@pytest.mark.parametrize(
    "formula",
    [
        "{PRD}",
        "{FLD}",
        "{HP}",
        "{NM}",
        "{APV}",
        "{FPV}",
        "{FG}",
        "{SCP}",
        "{IP}",
        "{BGEN}",
        "{LSHR}",
        "{PPN}",
        "{PNY}",
        "{TDAI}",
    ],
)
def test_evaluates_single_parameter_production_formulas(
    formula: str,
    representative_parameters: dict[str, list[float]],
) -> None:
    result = evaluate(formula, representative_parameters)

    assert_values_equal(result, [10.0, 20.0])


@pytest.mark.parametrize(
    ("formula", "expected"),
    [
        ("{APV}/{HEADCOUNT}", [1.0, 1.0]),
        ("{APC} + {AEC} - {FPC} - {FEC}", [0.0, 0.0]),
        ("{PCST1} + {PCST2}", [20.0, 40.0]),
        ("{PPST1} + {PPST2}", [20.0, 40.0]),
        ("{ENVT1} + {ENVT2}", [20.0, 40.0]),
        ("{FIRT1} + {FIRT2}", [20.0, 40.0]),
        ("{QN1P1} + {QN1P3}", [20.0, 40.0]),
        ("({FGBSGRM}/1000000)+({FGBSKGM}/1000)", [0.01001, 0.02002]),
        ("{AVLLINE} / {MSDP}", [1.0, 1.0]),
        ("(24*3600) - {LLOEE}", [86390.0, 86380.0]),
    ],
)
def test_evaluates_selected_production_formulas_with_expected_values(
    formula: str,
    expected: list[float],
    representative_parameters: dict[str, list[float]],
) -> None:
    result = evaluate(formula, representative_parameters)
    assert_values_equal(result, expected)
