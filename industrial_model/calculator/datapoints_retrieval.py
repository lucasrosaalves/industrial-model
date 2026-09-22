from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from cognite.client import AsyncCogniteClient
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from ._grid import CALENDAR_UNITS, parse_granularity
from ._timezone import to_utc
from ._timing import StageTimer, timed
from .exceptions import DatapointsRetrievalError
from .models import Series, TimeSeriesParameterBase

logger = logging.getLogger(__name__)

# Cognite's datapoints retrieve endpoint only accepts up to 100 time series
# per request, so larger requests must be chunked client-side. Chunks are
# fetched concurrently.
_MAX_TIME_SERIES_PER_REQUEST = 100

# ``DatapointsAPI._DPS_LIMIT_AGG``: the aggregate points one SDK request may
# return, shared by the aggregate series that request carries.
_AGGREGATE_POINT_BUDGET = 10_000


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
        """Fetch datapoints for every parameter's time series, unreduced.

        Returns one entry per parameter, each holding one series per
        ``timeseries_instance_id`` it references, in that order. Combining a
        parameter's series (when it references more than one) is the
        caller's responsibility - this class only retrieves and parses data.

        ``timezone`` is applied to every aggregate request in this retrieve
        and omitted from the query when unset. Aggregates with a timezone or a
        calendar granularity are requested again after each full page until
        the window is covered; raw queries and other aggregates are retrieved
        once. Naive ``start`` / ``end`` are read as UTC, like the rest of the
        calculator.
        """
        with timed(timer, "build_requests"):
            requests, index_mapping = self._build_requests(
                parameters, start, end, timezone
            )

        chunks = [
            requests[i : i + _MAX_TIME_SERIES_PER_REQUEST]
            for i in range(0, len(requests), _MAX_TIME_SERIES_PER_REQUEST)
        ]
        n_chunks = len(chunks)
        if timer is not None:
            timer.unique_timeseries = len(requests)
            timer.cdf_chunks = n_chunks
        log_debug = logger.isEnabledFor(logging.DEBUG)
        if log_debug:
            logger.debug(
                "built %s unique timeseries request(s) for %s parameter(s)",
                len(requests),
                len(parameters),
            )

        with timed(timer, "retrieve"):
            responses = await asyncio.gather(
                *(
                    self._retrieve_chunk(chunk, chunk_no, n_chunks, log_debug)
                    for chunk_no, chunk in enumerate(chunks, start=1)
                )
            )
        raw = [dp for response in responses for dp in response]

        with timed(timer, "parse"):
            return [
                [self._parse_datapoints(raw[idx], parameter) for idx in raw_indices]
                for parameter, raw_indices in zip(
                    parameters, index_mapping, strict=True
                )
            ]

    async def _retrieve_chunk(
        self,
        chunk: list[DatapointsQuery],
        chunk_no: int,
        n_chunks: int,
        log_debug: bool,
    ) -> Sequence[Datapoints]:
        started = time.perf_counter() if log_debug else None
        if any(_needs_manual_paging(query) for query in chunk):
            response = await self._retrieve_paged(chunk)
        else:
            response = await self._fetch_series(chunk)
        if started is not None:
            logger.debug(
                "retrieve chunk %s/%s: %s series in %.3fs",
                chunk_no,
                n_chunks,
                len(chunk),
                time.perf_counter() - started,
            )
        return response

    async def _fetch_series(
        self, queries: Sequence[DatapointsQuery]
    ) -> list[Datapoints]:
        response = await self._client.time_series.data.retrieve(instance_id=queries)
        return _coerce_series(response, len(queries))

    async def _retrieve_paged(self, chunk: list[DatapointsQuery]) -> list[Datapoints]:
        """Ask again after a full page, starting just after its last timestamp.

        A series is finished once a page is shorter than the smallest page
        the SDK could have handed it, or brings nothing new. CDF may round the
        advanced ``start`` down to the bucket that was already returned;
        ``_append_datapoints`` drops that overlap.

        ``query.start`` is advanced in place. The queries are created for one
        ``retrieve_datapoints`` call and the SDK copies them before use, so
        nothing else observes the mutation.
        """

        pending = list(range(len(chunk)))
        merged: list[Datapoints | None] = [None] * len(chunk)
        columns = [_aggregate_names(query) for query in chunk]
        while pending:
            batch = [chunk[index] for index in pending]
            pages = await self._fetch_series(batch)
            full_page = _min_page_size(batch)
            still_open: list[int] = []
            for index, page in zip(pending, pages, strict=True):
                stored = merged[index]
                if stored is None:
                    stored = _blank_datapoints(page)
                    merged[index] = stored
                added = _append_datapoints(stored, page, columns[index])
                query = chunk[index]
                if (
                    added == 0
                    or len(page.timestamp) < full_page
                    or not _needs_manual_paging(query)
                ):
                    continue
                query.start = int(stored.timestamp[-1]) + 1
                still_open.append(index)
            pending = still_open

        series = [item for item in merged if item is not None]
        if len(series) != len(chunk):
            raise DatapointsRetrievalError(
                f"expected {len(chunk)} datapoint series from CDF, got {len(series)}"
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


def _needs_manual_paging(query: DatapointsQuery) -> bool:
    """Whether the SDK may stop this query after its first full page.

    The SDK fetches aggregates with a timezone or a calendar granularity (any
    sub-hour or longer step counts once a timezone is set, see
    ``DatapointsQuery.use_cursors``) through a cursor, and
    ``BaseTaskOrchestrator._store_first_batch`` marks the series done when the
    first page is full but carries no ``nextCursor``. Those pages are followed
    here. Raw queries and aggregates without a timezone on fixed-length steps
    are split over time by the SDK itself and need nothing extra.
    """

    if not isinstance(query.granularity, str):
        return False
    if _has_timezone(query):
        return True
    parsed = parse_granularity(query.granularity)
    return parsed is not None and parsed[1] in CALENDAR_UNITS


def _has_timezone(query: DatapointsQuery) -> bool:
    timezone = query.timezone
    return timezone is not None and timezone is not DatapointsQuery._NOT_SET


def _aggregate_names(query: DatapointsQuery) -> list[str]:
    aggregates = query.aggregates
    if isinstance(aggregates, str):
        return [aggregates]
    if isinstance(aggregates, list):
        return [name for name in aggregates if isinstance(name, str)]
    return []


def _min_page_size(queries: Sequence[DatapointsQuery]) -> int:
    """Fewest points the SDK asks for on the first page of any series here.

    ``ChunkingDpsFetcher._create_initial_tasks`` spreads the aggregate queries
    of one retrieve over several requests and ``_find_initial_query_limits``
    shares ``_DPS_LIMIT_AGG`` evenly inside each; a single series in eager
    mode gets the whole budget. In every case a series is asked for at least
    ``budget // n_aggregate`` points, so a shorter page is complete and a
    longer one may be full. Using this floor instead of the exact split keeps
    the check independent of the SDK's concurrency settings, at the cost of
    at most one extra request per paged chunk.
    """

    n_aggregate = sum(1 for query in queries if isinstance(query.granularity, str))
    return max(1, _AGGREGATE_POINT_BUDGET // max(1, n_aggregate))


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
