from __future__ import annotations

import industrial_model.calculator as calculator
from industrial_model.calculator.formula_expression import evaluate


def test_public_names_match_all() -> None:
    # Every name advertised in ``__all__`` must actually be importable, so a
    # ``from industrial_model.calculator import *`` never raises AttributeError.
    for name in calculator.__all__:
        assert hasattr(calculator, name), name


def test_evaluate_is_re_exported_from_package() -> None:
    assert calculator.evaluate is evaluate


def test_all_contains_expected_public_surface() -> None:
    assert set(calculator.__all__) == {
        "CalculationResult",
        "Calculator",
        "CalculatorParameter",
        "CalculatorQuery",
        "DataPoint",
        "evaluate",
    }
