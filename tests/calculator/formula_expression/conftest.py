from __future__ import annotations

import pytest

from tests.calculator.formula_expression._support import (
    REPRESENTATIVE_FORMULAS,
    parameter_names_for,
)


@pytest.fixture
def representative_parameters() -> dict[str, list[float]]:
    return {name: [10.0, 20.0] for name in parameter_names_for(REPRESENTATIVE_FORMULAS)}
