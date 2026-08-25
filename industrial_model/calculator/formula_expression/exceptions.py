from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..exceptions import CalculatorError


class FormulaError(CalculatorError):
    """Base exception for formula errors."""


class InvalidFormulaError(FormulaError):
    """Raised when formula syntax or operations are not supported."""


class MissingParameterError(FormulaError):
    """Raised when a formula references parameters that were not provided."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = tuple(missing)
        joined = ", ".join(self.missing)
        super().__init__(f"missing formula parameter(s): {joined}")


class ParameterError(FormulaError):
    """Raised when a parameter value is not a valid numeric sequence."""


class ParameterLengthError(ParameterError):
    """Raised when referenced parameters do not all share the same length."""

    def __init__(self, lengths: Mapping[str, int]) -> None:
        self.lengths = dict(lengths)
        detail = ", ".join(
            f"{name!r} has {length}" for name, length in self.lengths.items()
        )
        super().__init__(f"parameter length mismatch: {detail}")


class MissingTimeAxisError(ParameterError):
    """Raised when a query has only constants and so has no time axis."""

    def __init__(self, aliases: Sequence[str]) -> None:
        self.aliases = tuple(aliases)
        joined = ", ".join(self.aliases)
        super().__init__(
            "query has no time-series parameter to define a time axis; "
            f"only constant parameter(s): {joined}"
        )


class ParameterTimestampError(ParameterError):
    """Raised when time-series parameters do not share the same timestamps."""

    def __init__(self, aliases: Sequence[str]) -> None:
        self.aliases = tuple(aliases)
        joined = ", ".join(self.aliases)
        super().__init__(
            f"parameter timestamp mismatch: {joined} do not share the same timestamps"
        )
