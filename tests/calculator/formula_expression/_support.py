from __future__ import annotations

import math
import random
import re
from collections.abc import Mapping, Sequence

import pytest

PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_REFERENCE_PREFIX = "__ref_param_"

REPRESENTATIVE_FORMULAS = [
    "(({APD} + {AED}) / {AVD}) - (({FPD} + {FED}) / {FVD})",
    "{APV}/{HEADCOUNT}",
    "({VMCM} - {FDCM} - {OFCM} - {PPCM} - {ECCM}) / {SVCM}",
    "\t{APV} - {FPV}",
    "{APC} + {AEC} - {FPC} - {FEC}",
    "{VMCM} - {FDCM} - {OFCM} - {PPCM} - {ECCM}",
    "{PRD}",
    "{FLD}",
    "({FGBSGRM}/1000000)+({FGBSKGM}/1000)",
    "({RMBSGRM}/1000000)+({RMBSKGM}/1000)",
    "{RMYVALUE} / {RMYCOUNT}",
    "({GBSGRM}/1000000)+({GBSKGM}/1000)",
    "({CBSGRM}/1000000)+({CBSKGM}/1000)",
    "{COPQ}",
    "{MAF}",
    "{QN1PE}",
    "{QN1P1} + {QN1P3}",
    "{A1KG}+({A1LBS}*453592)",
    "100 * ({AEKG}+{A0KG}+(({AELBS}+{A0LBS})*0.453592))"
    " / ({AEKG}+{A0KG}+{A1KG}+{R1KG}+{R2KG}+{R3KG}"
    "+(({AELBS}+{A0LBS}+{A1LBS}+{R1LBS}+{R2LBS}+{R3LBS})*0.453592))",
    "{R1KG}+{R2KG}+{R3KG}+(({R1LBS}+{R2LBS}+{R3LBS})*0.453592)",
    "{PCST1} + {PCST2}",
    "(200000 * ({CPPST1} + {CPPST2}+{EPPST1} + {EPPST2})) / {TWH}",
    "{PPST1} + {PPST2}",
    "{ENVT1} + {ENVT2}",
    "{FIRT1} + {FIRT2}",
    "{HP}",
    "{PPST3}",
    "{NM}",
    "(200000 * ({CPPST1} + {CPPST2})) / {CWH}",
    "(200000 * ({EPPST1} + {EPPST2})) / {EWH}",
    "{NMPCS}",
    "{ITLPCST2}",
    "{ITLPCST1}",
    "{ITLPCST3}",
    "{QN3}",
    "{QN1}",
    "{ITLPPST3}",
    "{ITLPPST2}",
    "{NMPPS}",
    "{ITLEVT3}",
    "{ITLEVT2}",
    "{NMENV}",
    "{ITLPPST1}",
    "{ITLEVT1}",
    "{NMFIR}",
    "{ITLFIRT3}",
    "{ITLFIRT2}",
    "{ITLFIRT1}",
    "{APV}",
    "{AVLLINE} / {MSDP}",
    "{QATLINE} / {MSDP}",
    "{PFMLINE} / {MSDP}",
    "{OEELINE} / {MSDP}",
    "(24*3600) - {LLOEE} - {ALOEE} - {PLOEE} - {QLOEE}",
    "{TEEPLINE} / {MSDP}",
    "(24*3600) - {LLOEE}",
    "(24*3600) - {LLOEE} - {ALOEE}",
    "(24*3600) - {LLOEE} - {ALOEE} - {PLOEE}",
    "{BSRMMB52}",
    "{FGBSMB52}",
    "{FPV}",
    "{FPC} + {FEC}",
    "{APC} + {AEC}",
    "{FG}",
    "100*({SCP})/({FG}+{IP}+{SCP})",
    "{SCP}",
    "{IP}",
    "{BGEN}",
    "{LSHR}",
    "{PPN}",
    "{PNY}",
    "{TDAI}",
]


def parameter_names_for(formulas: list[str]) -> set[str]:
    return {
        variable for formula in formulas for variable in PLACEHOLDER_RE.findall(formula)
    }


def assert_values_equal(
    actual: Sequence[float],
    expected: Sequence[float],
    *,
    rel: float | None = None,
    abs: float | None = None,
) -> None:
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected, strict=True):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        elif rel is not None or abs is not None:
            assert actual_value == pytest.approx(expected_value, rel=rel, abs=abs)
        else:
            assert actual_value == expected_value


def assert_values_allclose(
    actual: Sequence[float],
    expected: Sequence[float],
    *,
    rel: float = 1e-9,
    abs: float = 1e-9,
) -> None:
    assert_values_equal(actual, expected, rel=rel, abs=abs)


def reference_evaluate(
    formula: str,
    parameters: Mapping[str, Sequence[float]],
) -> tuple[float, ...]:
    """Independent oracle: evaluate the formula element-wise with Python's eval.

    This is a deliberately separate implementation from the library's AST-walking
    interpreter, so a match between the two is strong evidence of correctness.
    """

    normalized_formula = " ".join(formula.split())
    referenced = PLACEHOLDER_RE.findall(normalized_formula)
    expression = PLACEHOLDER_RE.sub(
        lambda match: f"{_REFERENCE_PREFIX}{match.group(1)}", normalized_formula
    )
    compiled = compile(expression, "<reference>", "eval")

    length = len(parameters[referenced[0]])
    results: list[float] = []
    for index in range(length):
        local_env = {
            f"{_REFERENCE_PREFIX}{name}": float(parameters[name][index])
            for name in referenced
        }
        results.append(float(eval(compiled, {"__builtins__": {}}, local_env)))  # noqa: S307
    return tuple(results)


def random_dataset(
    names: Sequence[str],
    *,
    length: int,
    seed: int = 0,
    low: float = 1.0,
    high: float = 1000.0,
) -> dict[str, list[float]]:
    """Build a deterministic random dataset.

    Values are strictly positive so that divisions and moduli in arbitrary
    formulas never hit zero denominators.
    """

    rng = random.Random(seed)
    return {name: [rng.uniform(low, high) for _ in range(length)] for name in names}
