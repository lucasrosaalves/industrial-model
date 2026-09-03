from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from cognite.client import CogniteClient
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from ._timing import StageTimer, timed
from .exceptions import DatapointsRetrievalError
from .models import Series, TimeSeriesParameterBase

logger = logging.getLogger(__name__)

# Cognite's datapoints retrieve endpoint only accepts up to 100 time series
# per request, so larger requests must be paginated client-side.
_MAX_TIME_SERIES_PER_REQUEST = 100


class DatapointsRetriever:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._client = cognite_client

    def retrieve_datapoints(
        self,
        parameters: Sequence[TimeSeriesParameterBase],
        start: datetime,
        end: datetime,
        timer: StageTimer | None = None,
    ) -> list[list[Series]]:
        """Fetch datapoints for every parameter's time series, unreduced.

        Returns one entry per parameter, each holding one series per
        ``timeseries_instance_id`` it references, in that order. Combining a
        parameter's series (when it references more than one) is the
        caller's responsibility - this class only retrieves and parses data.
        """
        with timed(timer, "build_requests"):
            requests, index_mapping = self._build_requests(parameters, start, end)

        n_chunks = (
            (len(requests) + _MAX_TIME_SERIES_PER_REQUEST - 1)
            // _MAX_TIME_SERIES_PER_REQUEST
            if requests
            else 0
        )
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

        raw: list[Datapoints] = []
        with timed(timer, "retrieve"):
            for chunk_no, i in enumerate(
                range(0, len(requests), _MAX_TIME_SERIES_PER_REQUEST), start=1
            ):
                chunk = requests[i : i + _MAX_TIME_SERIES_PER_REQUEST]
                started = time.perf_counter() if log_debug else None
                response = self._client.time_series.data.retrieve(instance_id=chunk)
                if started is not None:
                    logger.debug(
                        "retrieve chunk %s/%s: %s series in %.3fs",
                        chunk_no,
                        n_chunks,
                        len(chunk),
                        time.perf_counter() - started,
                    )
                if len(response) != len(chunk):
                    raise DatapointsRetrievalError(
                        f"expected {len(chunk)} datapoint series from CDF, "
                        f"got {len(response)}"
                    )
                raw.extend(response)

        with timed(timer, "parse"):
            return [
                [self._parse_datapoints(raw[idx], parameter) for idx in raw_indices]
                for parameter, raw_indices in zip(
                    parameters, index_mapping, strict=True
                )
            ]

    def _build_requests(
        self,
        parameters: Sequence[TimeSeriesParameterBase],
        start: datetime,
        end: datetime,
    ) -> tuple[list[DatapointsQuery], list[list[int]]]:
        dp_raw_queries: dict[tuple[str, str], DatapointsQuery] = {}
        dp_aggregate_queries: dict[tuple[tuple[str, str], str], DatapointsQuery] = {}

        requests: list[DatapointsQuery] = []
        index_mapping: list[list[int]] = []
        raw_request_index: dict[tuple[str, str], int] = {}
        agg_request_index: dict[tuple[tuple[str, str], str], int] = {}

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
