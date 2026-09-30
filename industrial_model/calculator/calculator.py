from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from cognite.client import CogniteClient

from ._grid import (
    aggregate_into_buckets,
    bucket_span,
    build_bucket_grid,
    expand_series_on_grid,
    formula_uses_rolling_average,
    min_granularity_seconds,
    shared_aggregate_granularity,
)
from ._timing import StageTimer, timed
from .datapoints_retrieval import DatapointsRetriever
from .exceptions import BucketGranularityError
from .formula_expression._compiler import CompiledFormula, compile_formula
from .formula_expression._runtime import evaluate_compiled
from .formula_expression.exceptions import (
    InvalidFormulaError,
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

_Window = tuple[datetime, datetime]


@dataclass(slots=True, frozen=True)
class _Bucketing:
    """The buckets a ``sum(...)`` / ``average(...)`` formula aggregates into."""

    granularity: str
    origin: datetime


@dataclass(slots=True, frozen=True)
class _QueryPlan:
    """One query resolved into what to fetch, over which window, and how.

    ``parameters`` are the query's time-series parameters, fetched exactly
    as declared. With ``bucketing`` set, the window covers the whole buckets
    of ``bucket_granularity`` and the results are aggregated by it.
    """

    query: CalculatorQuery
    formula: CompiledFormula
    parameters: Sequence[TimeSeriesParameterBase]
    window: _Window
    bucketing: _Bucketing | None


class Calculator:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._retriever = DatapointsRetriever(cognite_client.get_async_client())
        self._series_reducer = SeriesReducer()

    async def calculate(
        self,
        query: CalculatorQuery,
        start: datetime,
        end: datetime,
        *,
        timezone: str | None = None,
    ) -> CalculationResult:
        """Evaluate one query.

        ``timezone`` is keyword-only. It aligns hour-and-longer CDF aggregates
        to a local calendar; ``start`` / ``end`` stay UTC instants.
        """
        results = await self.calculate_multiples([query], start, end, timezone=timezone)
        return results[0]

    async def calculate_multiples(
        self,
        queries: list[CalculatorQuery],
        start: datetime,
        end: datetime,
        *,
        timezone: str | None = None,
    ) -> list[CalculationResult]:
        """Evaluate several queries in one retrieve.

        ``timezone`` is an IANA id or fixed offset (``America/New_York``,
        ``UTC+05:30``) applied to every hour-and-longer aggregate in the
        batch. Omit it for UTC calendar buckets. ``start`` / ``end`` are
        not reinterpreted. Raw and sub-hour retrieves are unchanged.
        The value is forwarded to CDF; invalid ids fail on retrieve.

        A ``sum(...)`` / ``average(...)`` query is fetched over the whole
        buckets of its ``bucket_granularity`` that ``[start, end)`` touches,
        so it may take one more retrieve than the rest.
        """
        timer = StageTimer() if logger.isEnabledFor(logging.DEBUG) else None
        ok = False
        try:
            plans = [_plan_query(query, start, end, timezone) for query in queries]
            leaf_series_by_plan = await self._retrieve(plans, timer, timezone)
            results = [
                self._calculate(plan, leaf_series, timezone, timer)
                for plan, leaf_series in zip(plans, leaf_series_by_plan, strict=True)
            ]
            ok = True
            return results
        finally:
            if timer is not None:
                logger.debug("%s", timer.format_summary(len(queries), ok=ok))

    async def _retrieve(
        self,
        plans: Sequence[_QueryPlan],
        timer: StageTimer | None,
        timezone: str | None,
    ) -> list[list[list[Series]]]:
        """Fetch every plan's parameters, one retrieve per distinct window.

        Windows are retrieved one after another: overlapping retrieves on the
        same client can silently truncate pages.
        """
        by_window: dict[_Window, list[tuple[int, TimeSeriesParameterBase]]] = {}
        for index, plan in enumerate(plans):
            for parameter in plan.parameters:
                by_window.setdefault(plan.window, []).append((index, parameter))

        leaf_series_by_plan: list[list[list[Series]]] = [[] for _ in plans]
        for (window_start, window_end), entries in by_window.items():
            fetched = await self._retriever.retrieve_datapoints(
                [parameter for _, parameter in entries],
                window_start,
                window_end,
                timer=timer,
                timezone=timezone,
            )
            for (index, _), leaf_series in zip(entries, fetched, strict=True):
                leaf_series_by_plan[index].append(leaf_series)
        return leaf_series_by_plan

    def _calculate(
        self,
        plan: _QueryPlan,
        leaf_series_by_parameter: list[list[Series]],
        timezone: str | None,
        timer: StageTimer | None = None,
    ) -> CalculationResult:
        query = plan.query
        it = iter(leaf_series_by_parameter)
        ts_aliases: list[str] = []
        ts_series: list[Series] = []

        with timed(timer, "reduce"):
            for ts_parameter in plan.parameters:
                leaf_series = next(it)
                if isinstance(ts_parameter, MultiTimeSeriesParameter):
                    series = self._series_reducer.reduce(
                        leaf_series, ts_parameter.reducer, ts_parameter.fill_value
                    )
                elif isinstance(ts_parameter, TimeSeriesParameter):
                    series = leaf_series[0]
                else:
                    raise TypeError(
                        f"unsupported parameter type: {type(ts_parameter).__name__}"
                    )
                ts_aliases.append(ts_parameter.alias)
                ts_series.append(series)

        if not ts_aliases and query.parameters:
            raise MissingTimeAxisError([p.alias for p in query.parameters])

        log_query = logger.isEnabledFor(logging.DEBUG)
        input_lengths = [len(series) for series in ts_series] if log_query else None
        with timed(timer, "align"):
            ts_series, filled = _align_or_fill_grid(
                plan,
                ts_aliases,
                ts_series,
                timezone,
                self._series_reducer,
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
            if plan.bucketing is None:
                values = evaluate_compiled(plan.formula, values_map)
                if filled:
                    timestamps, values, ts_series = _drop_nan_results(
                        timestamps, values, ts_series
                    )
                evaluated = list(zip(timestamps, values, strict=True))
            else:
                evaluated = _evaluate_buckets(
                    plan.formula,
                    plan.bucketing,
                    query,
                    timestamps,
                    values_map,
                    timezone,
                    self._series_reducer,
                )

        with timed(timer, "assemble"):
            inputs = {
                alias: _to_datapoints(series)
                for alias, series in zip(ts_aliases, ts_series, strict=True)
            }
            for parameter in query.parameters:
                if isinstance(parameter, ConstantParameter):
                    inputs[parameter.alias] = [
                        DataPoint(ts, parameter.value) for ts in timestamps
                    ]
            result = CalculationResult(
                query=query,
                datapoints=_to_datapoints(evaluated),
                inputs=inputs,
            )

        if log_query:
            logger.debug(
                "query formula=%s alignment=%s input_lengths=%s aligned_points=%s"
                " buckets=%s",
                _formula_preview(query.formula),
                query.alignment,
                input_lengths,
                len(timestamps),
                None if plan.bucketing is None else len(evaluated),
            )
        return result


def _plan_query(
    query: CalculatorQuery,
    start: datetime,
    end: datetime,
    timezone: str | None,
) -> _QueryPlan:
    formula = compile_formula(query.formula)
    parameters = [
        parameter
        for parameter in query.parameters
        if isinstance(parameter, TimeSeriesParameterBase)
    ]
    if not formula.bucket_terms:
        # A plain formula ignores bucket_granularity, so callers can always
        # pass their granularity.
        return _QueryPlan(query, formula, parameters, (start, end), None)

    if not parameters:
        raise MissingTimeAxisError([p.alias for p in query.parameters])
    # Outside sum() / average() the formula runs per bucket, where only
    # constants have a value.
    per_bucket = set(formula.variables)
    outside = [p.alias for p in parameters if p.alias in per_bucket]
    if outside:
        raise InvalidFormulaError(
            "time-series parameters must be inside sum() / average(): "
            + ", ".join(outside)
        )
    granularity = _bucket_granularity(query.bucket_granularity, parameters)
    origin, stop = bucket_span(start, end, granularity, timezone)
    return _QueryPlan(
        query,
        formula,
        parameters,
        (origin, stop),
        _Bucketing(granularity, origin),
    )


def _bucket_granularity(
    bucket_granularity: str | None,
    parameters: Sequence[TimeSeriesParameterBase],
) -> str:
    """Validate the granularity a bucketed query's results are aggregated by."""

    if bucket_granularity is None:
        raise BucketGranularityError(
            "a formula with sum() / average() needs bucket_granularity on the query "
            "(the granularity the results are aggregated by, e.g. '1d')"
        )
    bucket_seconds = min_granularity_seconds(bucket_granularity)
    if bucket_seconds is None:
        raise BucketGranularityError(
            f"unsupported bucket_granularity: {bucket_granularity!r}"
        )
    coarser = [
        f"{parameter.alias} ({parameter.granularity})"
        for parameter in parameters
        if parameter.aggregate_type is not None
        and parameter.granularity is not None
        and (min_granularity_seconds(parameter.granularity) or 0) > bucket_seconds
    ]
    if coarser:
        raise BucketGranularityError(
            f"parameter granularity is coarser than bucket_granularity "
            f"{bucket_granularity!r}: {', '.join(coarser)}"
        )
    return bucket_granularity


def _evaluate_buckets(
    formula: CompiledFormula,
    bucketing: _Bucketing,
    query: CalculatorQuery,
    timestamps: list[datetime],
    values_map: dict[str, list[float]],
    timezone: str | None,
    series_reducer: SeriesReducer,
) -> Series:
    """Run each bucket term per point, aggregate it, then the formula per bucket.

    A bucket is kept only when every term has a value there, and a ``NaN``
    result is dropped, so an empty bucket is omitted as CDF omits it.
    """

    term_buckets = [
        aggregate_into_buckets(
            list(
                zip(
                    timestamps,
                    evaluate_compiled(term.formula, values_map),
                    strict=True,
                )
            ),
            bucketing.origin,
            bucketing.granularity,
            timezone,
            term.aggregate,
        )
        for term in formula.bucket_terms
    ]
    aligned = series_reducer.align(term_buckets)
    bucket_starts = [ts for ts, _ in aligned[0]]
    bucket_values: dict[str, list[float]] = {
        term.key: [value for _, value in series]
        for term, series in zip(formula.bucket_terms, aligned, strict=True)
    }
    for parameter in query.parameters:
        if isinstance(parameter, ConstantParameter):
            bucket_values[parameter.alias] = [parameter.value] * len(bucket_starts)
    values = evaluate_compiled(formula, bucket_values)
    return [
        (ts, value)
        for ts, value in zip(bucket_starts, values, strict=True)
        if not math.isnan(value)
    ]


def _formula_preview(formula: str) -> str:
    compact = " ".join(formula.split())
    if len(compact) <= _FORMULA_PREVIEW:
        return compact
    return compact[: _FORMULA_PREVIEW - 3] + "..."


def _to_datapoints(series: Iterable[tuple[datetime, float]]) -> list[DataPoint]:
    return list(map(DataPoint._make, series))


def _align_or_fill_grid(
    plan: _QueryPlan,
    aliases: list[str],
    ts_series: list[Series],
    timezone: str | None,
    series_reducer: SeriesReducer,
) -> tuple[list[Series], bool]:
    query = plan.query
    fill_values = [parameter.fill_value for parameter in plan.parameters]
    granularity = shared_aggregate_granularity(plan.parameters)
    if (
        granularity is not None
        and ts_series
        and all(ts_series)
        and formula_uses_rolling_average(query.formula)
    ):
        start, end = plan.window
        references = [timestamp for series in ts_series for timestamp, _ in series]
        grid = build_bucket_grid(start, end, granularity, timezone, references)
        if grid:
            if query.alignment == "strict":
                _require_aligned_timestamps(aliases, ts_series)
            return [
                expand_series_on_grid(series, grid, fill)
                for series, fill in zip(ts_series, fill_values, strict=True)
            ], True
    return (
        _align_series(query.alignment, aliases, ts_series, fill_values, series_reducer),
        False,
    )


def _align_series(
    mode: AlignmentMode,
    aliases: list[str],
    ts_series: list[Series],
    fill_values: list[float | None],
    series_reducer: SeriesReducer,
) -> list[Series]:
    if mode == "strict":
        _require_aligned_timestamps(aliases, ts_series)
        return ts_series
    if any(fill is not None for fill in fill_values):
        return series_reducer.align_filled(ts_series, fill_values)
    return series_reducer.align(ts_series)


def _drop_nan_results(
    timestamps: list[datetime],
    values: tuple[float, ...],
    ts_series: list[Series],
) -> tuple[list[datetime], tuple[float, ...], list[Series]]:
    keep = [not math.isnan(value) for value in values]
    return (
        [timestamp for timestamp, flag in zip(timestamps, keep, strict=True) if flag],
        tuple(value for value, flag in zip(values, keep, strict=True) if flag),
        [
            [point for point, flag in zip(series, keep, strict=True) if flag]
            for series in ts_series
        ],
    )


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
