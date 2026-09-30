from __future__ import annotations


class CalculatorError(Exception):
    """Base exception for every error raised by the calculator package.

    ``FormulaError`` and its subclasses derive from this, so a caller that
    only wants to distinguish "the calculator failed" from "something else
    failed" can catch this single type.
    """


class DatapointsRetrievalError(CalculatorError):
    """Raised when CDF returns datapoints the retriever cannot use."""


class BucketGranularityError(CalculatorError):
    """Raised when a query's ``bucket_granularity`` does not fit its formula.

    A ``sum(...)`` / ``average(...)`` formula needs a known
    ``bucket_granularity`` no finer than any aggregated parameter. Other
    formulas ignore it.
    """
