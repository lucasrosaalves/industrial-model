from __future__ import annotations


class CalculatorError(Exception):
    """Base exception for every error raised by the calculator package.

    ``FormulaError`` and its subclasses derive from this, so a caller that
    only wants to distinguish "the calculator failed" from "something else
    failed" can catch this single type.
    """


class DatapointsRetrievalError(CalculatorError):
    """Raised when CDF returns datapoints the retriever cannot use."""
