from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from cognite.client.data_classes.datapoint_aggregates import Aggregate
from pydantic import BaseModel, Field, model_validator

from industrial_model.models import InstanceId


class DataPoint(BaseModel):
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


class CalculationResult(BaseModel):
    query: CalculatorQuery
    datapoints: list[DataPoint]
