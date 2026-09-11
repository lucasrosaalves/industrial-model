from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from cognite.client import CogniteClient

from ._timing import StageTimer, timed
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

logger = logging.getLogger(__name__)

_FORMULA_PREVIEW = 80


class Calculator:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._retriever = DatapointsRetriever(cognite_client)
        self._series_reducer = SeriesReducer()

    def calculate(
        self,
        query: CalculatorQuery,
        start: datetime,
        end: datetime,
        include_inputs: bool = True,
    ) -> CalculationResult:
        return self.calculate_multiples([query], start, end, include_inputs)[0]

    def calculate_multiples(
        self,
        queries: list[CalculatorQuery],
        start: datetime,
        end: datetime,
        include_inputs: bool = True,
    ) -> list[CalculationResult]:
        timer = StageTimer() if logger.isEnabledFor(logging.DEBUG) else None
        ok = False
        try:
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
                ts_parameters, start, end, timer=timer
            )

            results: list[CalculationResult] = []
            offset = 0
            for query, count in zip(queries, ts_counts, strict=True):
                results.append(
                    self._calculate(
                        query,
                        leaf_series_by_parameter[offset : offset + count],
                        timer,
                        include_inputs,
                    )
                )
                offset += count
            ok = True
            return results
        finally:
            if timer is not None:
                logger.debug("%s", timer.format_summary(len(queries), ok=ok))

    def _calculate(
        self,
        query: CalculatorQuery,
        leaf_series_by_parameter: list[list[Series]],
        timer: StageTimer | None = None,
        include_inputs: bool = True,
    ) -> CalculationResult:
        it = iter(leaf_series_by_parameter)
        ts_aliases: list[str] = []
        ts_series: list[Series] = []

        with timed(timer, "reduce"):
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

        log_query = logger.isEnabledFor(logging.DEBUG)
        input_lengths = [len(series) for series in ts_series] if log_query else None
        with timed(timer, "align"):
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

        with timed(timer, "evaluate"):
            values = evaluate(query.formula, values_map)

        with timed(timer, "assemble"):
            inputs: dict[str, list[DataPoint]] = {}
            if include_inputs:
                inputs = {
                    alias: _to_datapoints(series)
                    for alias, series in zip(ts_aliases, ts_series, strict=True)
                }
                for parameter in query.parameters:
                    if isinstance(parameter, ConstantParameter):
                        inputs[parameter.alias] = [
                            DataPoint(timestamp=ts, value=parameter.value)
                            for ts in timestamps
                        ]
            result = CalculationResult(
                query=query,
                datapoints=_to_datapoints(zip(timestamps, values, strict=True)),
                inputs=inputs,
            )

        if log_query:
            logger.debug(
                "query formula=%s alignment=%s input_lengths=%s aligned_points=%s",
                _formula_preview(query.formula),
                query.alignment,
                input_lengths,
                len(timestamps),
            )
        return result


def _formula_preview(formula: str) -> str:
    compact = " ".join(formula.split())
    if len(compact) <= _FORMULA_PREVIEW:
        return compact
    return compact[: _FORMULA_PREVIEW - 3] + "..."


def _to_datapoints(series: Iterable[tuple[datetime, float]]) -> list[DataPoint]:
    return [DataPoint(timestamp=ts, value=value) for ts, value in series]


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
