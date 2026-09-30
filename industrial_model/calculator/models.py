from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Literal, NamedTuple, TypeAlias

from cognite.client.data_classes.datapoint_aggregates import Aggregate
from pydantic import BaseModel, Field, model_validator

from industrial_model.models import InstanceId


class DataPoint(NamedTuple):
    """A timestamped numeric value."""

    timestamp: datetime
    value: float


ReducerType: TypeAlias = Literal["min", "max", "sum", "average"]
AlignmentMode: TypeAlias = Literal["intersect", "strict"]

# One time series' datapoints, ascending by timestamp once normalized.
Series: TypeAlias = list[tuple[datetime, float]]


class ConstantParameter(BaseModel):
    type: Literal["constant"] = "constant"
    alias: str
    value: float


class TimeSeriesParameterBase(BaseModel):
    alias: str
    aggregate_type: Aggregate | None = None
    granularity: str | None = None
    # Value used at a timestamp where this series has no point but another
    # parameter does (``0`` for a count). ``None`` drops that timestamp.
    fill_value: float | None = Field(default=None, allow_inf_nan=False)

    def instance_ids(self) -> Sequence[InstanceId]:
        raise NotImplementedError

    def require_granularity(self) -> str:
        """Return the granularity that ``aggregate_type`` needs.

        Construction already rejects an aggregate without a granularity, so
        this only fires for a model built with ``model_construct`` (which
        skips validators). It also narrows ``str | None`` down to ``str``.
        """
        if self.granularity is None:
            raise ValueError(
                f"Missing granularity for '{self.alias}' "
                f"with aggregate '{self.aggregate_type}'"
            )
        return self.granularity

    @model_validator(mode="after")
    def _validate_aggregate_granularity(self) -> TimeSeriesParameterBase:
        if self.aggregate_type is not None:
            self.require_granularity()
        return self


class TimeSeriesParameter(TimeSeriesParameterBase):
    type: Literal["single_timeseries"] = "single_timeseries"
    timeseries_instance_id: InstanceId

    def instance_ids(self) -> Sequence[InstanceId]:
        return (self.timeseries_instance_id,)


class MultiTimeSeriesParameter(TimeSeriesParameterBase):
    type: Literal["multi_timeseries"] = "multi_timeseries"
    timeseries_instance_ids: list[InstanceId]
    reducer: ReducerType

    def instance_ids(self) -> Sequence[InstanceId]:
        return self.timeseries_instance_ids

    @model_validator(mode="after")
    def _validate_timeseries_instance_ids(self) -> MultiTimeSeriesParameter:
        if len(self.timeseries_instance_ids) < 2:
            raise ValueError(
                f"'{self.alias}' must reference at least two timeseries; "
                "use a single-timeseries parameter for one"
            )
        if len(set(self.timeseries_instance_ids)) != len(self.timeseries_instance_ids):
            raise ValueError(f"'{self.alias}' has duplicate timeseries instance ids")
        return self


CalculatorParameter = Annotated[
    ConstantParameter | TimeSeriesParameter | MultiTimeSeriesParameter,
    Field(discriminator="type"),
]


class CalculatorQuery(BaseModel):
    formula: str
    parameters: list[CalculatorParameter]
    alignment: AlignmentMode = "intersect"
    # Granularity the results of a ``sum(...)`` / ``average(...)`` formula
    # are aggregated by, after it runs on the parameters as fetched. Required
    # by those formulas and ignored by every other one.
    bucket_granularity: str | None = None

    @model_validator(mode="after")
    def _validate_unique_aliases(self) -> CalculatorQuery:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for parameter in self.parameters:
            if parameter.alias in seen:
                duplicates.add(parameter.alias)
            seen.add(parameter.alias)
        if duplicates:
            raise ValueError(
                f"duplicate parameter alias(es): {', '.join(sorted(duplicates))}"
            )
        return self

    @model_validator(mode="after")
    def _validate_fill_alignment(self) -> CalculatorQuery:
        if self.alignment != "strict":
            return self
        filled = [
            parameter.alias
            for parameter in self.parameters
            if isinstance(parameter, TimeSeriesParameterBase)
            and parameter.fill_value is not None
        ]
        if filled:
            raise ValueError(
                "fill_value needs alignment='intersect'; strict alignment "
                f"never fills: {', '.join(filled)}"
            )
        return self


@dataclass(slots=True, frozen=True)
class CalculationResult:
    """Output of ``Calculator.calculate``."""

    query: CalculatorQuery
    datapoints: list[DataPoint]
    # Index-aligned with ``datapoints``, except for a ``sum(...)`` /
    # ``average(...)`` formula: there each input holds the aligned points the
    # formula ran on, before its results were aggregated into ``datapoints``.
    inputs: dict[str, list[DataPoint]] = field(default_factory=dict)
