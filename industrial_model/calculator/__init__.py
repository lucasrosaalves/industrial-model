import logging

from .calculator import Calculator
from .exceptions import CalculatorError
from .formula_expression import compile_formula, evaluate
from .formula_expression.exceptions import InvalidFormulaError
from .models import (
    AlignmentMode,
    CalculationResult,
    CalculatorParameter,
    CalculatorQuery,
    ConstantParameter,
    DataPoint,
    MultiTimeSeriesParameter,
    ReducerType,
    TimeSeriesParameter,
)

__all__ = [
    "AlignmentMode",
    "CalculationResult",
    "Calculator",
    "CalculatorError",
    "CalculatorParameter",
    "CalculatorQuery",
    "ConstantParameter",
    "DataPoint",
    "InvalidFormulaError",
    "MultiTimeSeriesParameter",
    "ReducerType",
    "TimeSeriesParameter",
    "compile_formula",
    "evaluate",
]

# Library logging: no handlers of our own. Applications configure this logger.
logging.getLogger(__name__).addHandler(logging.NullHandler())
