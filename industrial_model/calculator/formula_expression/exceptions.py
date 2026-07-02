from __future__ import annotations

from collections.abc import Mapping


class FormulaError(Exception):
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
