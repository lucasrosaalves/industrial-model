from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from cognite.client import AsyncCogniteClient, global_config
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from ._timezone import to_utc
from ._timing import StageTimer, timed
from .exceptions import DatapointsRetrievalError
from .models import Series, TimeSeriesParameterBase

logger = logging.getLogger(__name__)

# Mirrors of the SDK's request planning (``DatapointsAPI`` /
# ``ChunkingDpsFetcher._create_initial_tasks``): the points one request may
# return for aggregate and raw series respectively, and the most time series
# one request may carry.
_AGGREGATE_POINT_BUDGET = 10_000
_RAW_POINT_BUDGET = 100_000
_MAX_TIME_SERIES_PER_REQUEST = 100


class DatapointsRetriever:
    def __init__(self, cognite_client: AsyncCogniteClient) -> None:
        self._client = cognite_client

    async def retrieve_datapoints(
        self,
        parameters: Sequence[TimeSeriesParameterBase],
        start: datetime,
        end: datetime,
        timer: StageTimer | None = None,
        timezone: str | None = None,
    ) -> list[list[Series]]:
        with timed(timer, "build_requests"):
            requests, index_mapping = self._build_requests(
                parameters, start, end, timezone
            )

        if timer is not None:
            timer.unique_timeseries = len(requests)
        logger.debug(
            "built %s unique timeseries request(s) for %s parameter(s)",
            len(requests),
            len(parameters),
        )

        with timed(timer, "retrieve"):
            started = time.perf_counter()
            raw = await self._retrieve_paged(requests)
            logger.debug(
                "retrieve: %s series in %.3fs",
                len(requests),
                time.perf_counter() - started,
            )

        with timed(timer, "parse"):
            return [
                [self._parse_datapoints(raw[idx], parameter) for idx in raw_indices]
                for parameter, raw_indices in zip(
                    parameters, index_mapping, strict=True
                )
            ]

    async def _fetch_series(
        self, queries: Sequence[DatapointsQuery]
    ) -> list[Datapoints]:
        response = await self._client.time_series.data.retrieve(instance_id=queries)
        return _coerce_series(response, len(queries))

    async def _retrieve_paged(self, queries: list[DatapointsQuery]) -> list[Datapoints]:
        """Ask again after a possibly full page, from just after its last point.

        A series is finished once a page is shorter than the smallest first
        page the SDK could have handed it (see ``_min_page_sizes``), or brings
        nothing new. CDF may round the advanced ``start`` down to the bucket
        that was already returned; ``_append_datapoints`` drops that overlap.

        ``query.start`` is advanced in place. The queries are created for one
        ``retrieve_datapoints`` call and the SDK copies them before use, so
        nothing else observes the mutation.
        """

        pending = list(range(len(queries)))
        merged: list[Datapoints | None] = [None] * len(queries)
        columns = [_value_columns(query) for query in queries]
        while pending:
            batch = [queries[index] for index in pending]
            pages = await self._fetch_series(batch)
            full_aggregate, full_raw = _min_page_sizes(batch)
            still_open: list[int] = []
            for index, page in zip(pending, pages, strict=True):
                stored = merged[index]
                if stored is None:
                    stored = _blank_datapoints(page)
                    merged[index] = stored
                added = _append_datapoints(stored, page, columns[index])
                query = queries[index]
                full_page = full_aggregate if _is_aggregate(query) else full_raw
                if added == 0 or len(page.timestamp) < full_page:
                    continue
                query.start = int(stored.timestamp[-1]) + 1
                still_open.append(index)
            pending = still_open

        series = [item for item in merged if item is not None]
        if len(series) != len(queries):
            raise DatapointsRetrievalError(
                f"expected {len(queries)} datapoint series from CDF, got {len(series)}"
            )
        return series

    def _build_requests(
        self,
        parameters: Sequence[TimeSeriesParameterBase],
        start: datetime,
        end: datetime,
        timezone: str | None = None,
    ) -> tuple[list[DatapointsQuery], list[list[int]]]:
        dp_raw_queries: dict[tuple[str, str], DatapointsQuery] = {}
        dp_aggregate_queries: dict[tuple[tuple[str, str], str], DatapointsQuery] = {}

        requests: list[DatapointsQuery] = []
        index_mapping: list[list[int]] = []
        raw_request_index: dict[tuple[str, str], int] = {}
        agg_request_index: dict[tuple[tuple[str, str], str], int] = {}

        # The SDK reads a naive datetime as local time; the calculator reads
        # it as UTC. Pin the instants so both sides see the same window.
        start = to_utc(start)
        end = to_utc(end)

        for parameter in parameters:
            raw_indices: list[int] = []

            for instance_id in parameter.instance_ids():
                ts_key = instance_id.as_tuple()

                if parameter.aggregate_type is None:
                    if ts_key not in dp_raw_queries:
                        request = DatapointsQuery(
                            instance_id=ts_key,
                            start=start,
                            end=end,
                            granularity=None,
                        )
                        dp_raw_queries[ts_key] = request
                        raw_request_index[ts_key] = len(requests)
                        requests.append(request)
                    raw_indices.append(raw_request_index[ts_key])
                    continue

                granularity = parameter.require_granularity()
                agg_key = (ts_key, granularity)
                if agg_key not in dp_aggregate_queries:
                    request = DatapointsQuery(
                        instance_id=ts_key,
                        aggregates=[parameter.aggregate_type],
                        granularity=granularity,
                        start=start,
                        end=end,
                    )
                    if timezone is not None:
                        request.timezone = timezone
                    dp_aggregate_queries[agg_key] = request
                    agg_request_index[agg_key] = len(requests)
                    requests.append(request)
                else:
                    entry = dp_aggregate_queries[agg_key]
                    if not isinstance(entry.aggregates, list):
                        raise TypeError(
                            f"expected aggregates to be a list, "
                            f"got {type(entry.aggregates).__name__}"
                        )
                    if parameter.aggregate_type not in entry.aggregates:
                        entry.aggregates.append(parameter.aggregate_type)

                raw_indices.append(agg_request_index[agg_key])

            index_mapping.append(raw_indices)

        return requests, index_mapping

    def _parse_datapoints(
        self,
        dp: Datapoints,
        parameter: TimeSeriesParameterBase,
    ) -> Series:
        if not isinstance(dp, Datapoints):
            raise DatapointsRetrievalError(
                f"expected Datapoints, got {type(dp).__name__}"
            )
        if dp.type != "numeric":
            raise DatapointsRetrievalError(
                f"expected numeric datapoints, got {dp.type}"
            )

        col = (
            dp.value
            if parameter.aggregate_type is None
            else getattr(dp, parameter.aggregate_type)
        ) or []

        if not isinstance(col, list):
            raise DatapointsRetrievalError(
                f"expected a list of values, got {type(col).__name__}"
            )

        timestamps = dp.timestamp or []
        if not isinstance(timestamps, list):
            raise DatapointsRetrievalError(
                f"expected a list of timestamps, got {type(timestamps).__name__}"
            )

        if len(timestamps) != len(col):
            column = parameter.aggregate_type or "value"
            raise DatapointsRetrievalError(
                f"CDF returned {len(timestamps)} timestamp(s) but "
                f"{len(col)} '{column}' value(s) for '{parameter.alias}'"
            )

        return [
            (datetime.fromtimestamp(ts / 1000, tz=UTC), cast(float, val))
            for ts, val in zip(timestamps, col, strict=True)
            if val is not None
        ]


def _is_aggregate(query: DatapointsQuery) -> bool:
    return isinstance(query.granularity, str)


def _value_columns(query: DatapointsQuery) -> list[str]:
    """Names of the ``Datapoints`` attributes that carry this query's values."""

    if not _is_aggregate(query):
        return ["value"]
    aggregates = query.aggregates
    if isinstance(aggregates, str):
        return [aggregates]
    if isinstance(aggregates, list):
        return [name for name in aggregates if isinstance(name, str)]
    return []


def _read_concurrency() -> int:
    """The SDK's datapoints read concurrency (requests in flight per client)."""

    return int(global_config.concurrency_settings.datapoints.read)


def _min_page_sizes(queries: Sequence[DatapointsQuery]) -> tuple[int, int]:
    """Fewest points the SDK asks for on the first page of any series here.

    Returns the floor for aggregate and for raw series. With more series than
    the read concurrency, ``ChunkingDpsFetcher._create_initial_tasks`` spreads
    them over ``max(read, ceil(n / 100))`` requests (aggregate and raw split
    independently) and ``_find_initial_query_limits`` shares the request's
    point budget evenly among the series it carries. A series that fits the
    eager path (``n <= read``) is asked for the whole budget. Either way a
    page shorter than the floor is complete; one at least as long may be full.
    """

    n_aggregate = sum(1 for query in queries if _is_aggregate(query))
    n_raw = len(queries) - n_aggregate
    read = max(1, _read_concurrency())
    n_requests = max(read, math.ceil(len(queries) / _MAX_TIME_SERIES_PER_REQUEST))

    def floor(budget: int, count: int) -> int:
        per_request = max(1, math.ceil(count / n_requests))
        return max(1, budget // per_request)

    return floor(_AGGREGATE_POINT_BUDGET, n_aggregate), floor(_RAW_POINT_BUDGET, n_raw)


def _coerce_series(response: object, expected: int) -> list[Datapoints]:
    if isinstance(response, Datapoints):
        items: Sequence[object] = [response]
    elif isinstance(response, Sequence) and not isinstance(response, str | bytes):
        items = response
    else:
        raise DatapointsRetrievalError(
            f"expected datapoint series from CDF, got {type(response).__name__}"
        )
    series: list[Datapoints] = []
    for item in items:
        if not isinstance(item, Datapoints):
            raise DatapointsRetrievalError(
                f"expected Datapoints, got {type(item).__name__}"
            )
        series.append(item)
    if len(series) != expected:
        raise DatapointsRetrievalError(
            f"expected {expected} datapoint series from CDF, got {len(series)}"
        )
    return series


def _blank_datapoints(page: Datapoints) -> Datapoints:
    return Datapoints(
        id=page.id,
        external_id=page.external_id,
        instance_id=page.instance_id,
        is_string=page.is_string,
        is_step=page.is_step,
        type=page.type,
        unit=page.unit,
        unit_external_id=page.unit_external_id,
        granularity=page.granularity,
        timestamp=[],
        timezone=page.timezone,
    )


def _append_datapoints(
    base: Datapoints, page: Datapoints, columns: Sequence[str]
) -> int:
    incoming = page.timestamp or []
    start = 0
    if base.timestamp:
        cutoff = base.timestamp[-1]
        while start < len(incoming) and incoming[start] <= cutoff:
            start += 1
    added = len(incoming) - start
    if added == 0:
        return 0
    base.timestamp.extend(incoming[start:])
    for name in columns:
        values = getattr(page, name, None)
        if not isinstance(values, list):
            continue
        piece = values[start:]
        current = getattr(base, name, None)
        if isinstance(current, list):
            current.extend(piece)
        else:
            setattr(base, name, list(piece))
    return added
