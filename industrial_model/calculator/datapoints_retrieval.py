from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from cognite.client import CogniteClient
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from .models import CalculatorParameter


class DatapointsRetriever:
    def __init__(self, cognite_client: CogniteClient) -> None:
        self._client = cognite_client

    def retrieve_datapoints(
        self,
        parameters: list[CalculatorParameter],
        start: datetime,
        end: datetime,
    ) -> list[list[tuple[datetime, float]]]:
        requests, index_mapping = self._build_requests(parameters, start, end)
        raw = self._client.time_series.data.retrieve(instance_id=requests)

        return [
            self._parse_datapoints(raw[index_mapping[idx]], parameter)
            for idx, parameter in enumerate(parameters)
        ]

    def _build_requests(
        self,
        parameters: list[CalculatorParameter],
        start: datetime,
        end: datetime,
    ) -> tuple[list[DatapointsQuery], dict[int, int]]:
        dp_raw_queries: dict[tuple[str, str], DatapointsQuery] = {}
        dp_aggregate_queries: dict[tuple[tuple[str, str], str], DatapointsQuery] = {}

        requests: list[DatapointsQuery] = []
        index_mapping: dict[int, int] = {}
        raw_request_index: dict[tuple[str, str], int] = {}
        agg_request_index: dict[tuple[tuple[str, str], str], int] = {}

        for idx, parameter in enumerate(parameters):
            ts_key = parameter.timeseries_instance_id.as_tuple()

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
                index_mapping[idx] = raw_request_index[ts_key]
                continue

            if parameter.granularity is None:
                raise ValueError(
                    f"""Missing granularity for '{parameter.alias}'
                       with aggregate '{parameter.aggregate_type}'"""
                )

            agg_key = (ts_key, parameter.granularity)
            if agg_key not in dp_aggregate_queries:
                request = DatapointsQuery(
                    instance_id=ts_key,
                    aggregates=[parameter.aggregate_type],
                    granularity=parameter.granularity,
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

            index_mapping[idx] = agg_request_index[agg_key]

        return requests, index_mapping

    def _parse_datapoints(
        self,
        dp: Datapoints,
        parameter: CalculatorParameter,
    ) -> list[tuple[datetime, float]]:
        if not isinstance(dp, Datapoints):
            raise TypeError(f"expected Datapoints, got {type(dp).__name__}")
        if dp.type != "numeric":
            raise ValueError(f"expected numeric datapoints, got {dp.type}")

        col = (
            dp.value
            if parameter.aggregate_type is None
            else getattr(dp, parameter.aggregate_type)
        ) or []

        if not isinstance(col, list):
            raise TypeError(f"expected a list of values, got {type(col).__name__}")

        return [
            (datetime.fromtimestamp(ts / 1000, tz=UTC), cast(float, val))
            for ts, val in zip(dp.timestamp or (), col, strict=False)
            if val is not None
        ]
