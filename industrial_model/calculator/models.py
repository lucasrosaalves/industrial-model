from __future__ import annotations

from datetime import datetime

from cognite.client.data_classes.datapoint_aggregates import Aggregate
from pydantic import BaseModel

from industrial_model.models import InstanceId


class CalculationResult(BaseModel):
    timestamps: list[datetime]
    values: list[float]


class TimeSeriesParameter(BaseModel):
    timeseries_instance_id: InstanceId
    aggregate_type: Aggregate | None = None
    granularity: str | None = None


class CalculatorParameter(TimeSeriesParameter):
    alias: str


class CalculatorQuery(BaseModel):
    formula: str
    parameters: list[CalculatorParameter]
