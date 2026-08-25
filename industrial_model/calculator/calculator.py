from __future__ import annotations

from datetime import datetime

from cognite.client import CogniteClient

from .datapoints_retrieval import DatapointsRetriever
from .formula_expression import evaluate
from .formula_expression.exceptions import (
    MissingTimeAxisError,
    ParameterTimestampError,
)
from .models import (
    AlignmentMode,
    CalculationResult,
    CalculatorQuery,
    ConstantParameter,
    DataPoint,
    MultiTimeSeriesParameter,
    Series,
    TimeSeriesParameter,
    TimeSeriesParameterBase,
)
from .series_reducer import SeriesReducer


class Calculator:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._retriever = DatapointsRetriever(cognite_client)
        self._series_reducer = SeriesReducer()

    def calculate(
        self, query: CalculatorQuery, start: datetime, end: datetime
    ) -> CalculationResult:
        return self.calculate_multiples([query], start, end)[0]

    def calculate_multiples(
        self, queries: list[CalculatorQuery], start: datetime, end: datetime
    ) -> list[CalculationResult]:
        ts_counts = [
            sum(
                1
                for parameter in query.parameters
                if isinstance(parameter, TimeSeriesParameterBase)
            )
            for query in queries
        ]
        ts_parameters = [
            parameter
            for query in queries
            for parameter in query.parameters
            if isinstance(parameter, TimeSeriesParameterBase)
        ]
        leaf_series_by_parameter = self._retriever.retrieve_datapoints(
            ts_parameters, start, end
        )

        results: list[CalculationResult] = []
        offset = 0
        for query, count in zip(queries, ts_counts, strict=True):
            results.append(
                self._calculate(
                    query, leaf_series_by_parameter[offset : offset + count]
                )
            )
            offset += count
        return results

    def _calculate(
        self,
        query: CalculatorQuery,
        leaf_series_by_parameter: list[list[Series]],
    ) -> CalculationResult:
        it = iter(leaf_series_by_parameter)
        ts_aliases: list[str] = []
        ts_series: list[Series] = []

        for parameter in query.parameters:
            if not isinstance(parameter, TimeSeriesParameterBase):
                continue
            leaf_series = next(it)
            if isinstance(parameter, MultiTimeSeriesParameter):
                series = self._series_reducer.reduce(leaf_series, parameter.reducer)
            elif isinstance(parameter, TimeSeriesParameter):
                series = leaf_series[0]
            else:
                raise TypeError(
                    f"unsupported parameter type: {type(parameter).__name__}"
                )
            ts_aliases.append(parameter.alias)
            ts_series.append(series)

        if not ts_aliases and query.parameters:
            raise MissingTimeAxisError([p.alias for p in query.parameters])

        ts_series = _align_series(
            query.alignment, ts_aliases, ts_series, self._series_reducer
        )
        timestamps = [ts for ts, _ in ts_series[0]] if ts_series else []
        values_map = {
            alias: [val for _, val in series]
            for alias, series in zip(ts_aliases, ts_series, strict=True)
        }

        for parameter in query.parameters:
            if isinstance(parameter, ConstantParameter):
                values_map[parameter.alias] = [parameter.value] * len(timestamps)

        values = evaluate(query.formula, values_map)
        return CalculationResult(
            query=query,
            datapoints=[
                DataPoint(timestamp=ts, value=value)
                for ts, value in zip(timestamps, values, strict=True)
            ],
        )


def _align_series(
    mode: AlignmentMode,
    aliases: list[str],
    ts_series: list[Series],
    series_reducer: SeriesReducer,
) -> list[Series]:
    if mode == "strict":
        _require_aligned_timestamps(aliases, ts_series)
        return ts_series
    return series_reducer.align(ts_series)


def _require_aligned_timestamps(
    aliases: list[str],
    ts_series: list[Series],
) -> None:
    if not ts_series:
        return

    timestamps = [ts for ts, _ in ts_series[0]]
    mismatched = [
        alias
        for alias, series in zip(aliases[1:], ts_series[1:], strict=True)
        if [ts for ts, _ in series] != timestamps
    ]
    if mismatched:
        raise ParameterTimestampError([aliases[0], *mismatched])
