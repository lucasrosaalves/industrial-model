from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from unittest.mock import MagicMock

import pytest
from cognite.client.data_classes.datapoints import Datapoints, DatapointsList

from industrial_model.calculator.datapoints_retrieval import DatapointsRetriever
from industrial_model.calculator.models import CalculatorParameter
from industrial_model.models import InstanceId

_START = datetime(2024, 1, 1, tzinfo=UTC)
_END = datetime(2024, 1, 2, tzinfo=UTC)


def _param(
    alias: str,
    *,
    external_id: str = "x",
    space: str = "s",
    aggregate: str | None = None,
    granularity: str | None = None,
) -> CalculatorParameter:
    return CalculatorParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
        aggregate_type=aggregate,  # type: ignore[arg-type]
        granularity=granularity,
    )


def _datapoints(
    *,
    external_id: str = "x",
    timestamps: list[int] | None = None,
    value: list[float] | None = None,
    dp_type: Literal["numeric", "string", "state"] = "numeric",
    **aggregate_columns: list[float],
) -> Datapoints:
    dp = Datapoints(
        id=1,
        is_string=False,
        is_step=False,
        type=dp_type,
        external_id=external_id,
        instance_id=MagicMock(external_id=external_id),
        timestamp=timestamps,
        value=value,
    )
    for name, column in aggregate_columns.items():
        setattr(dp, name, column)
    return dp


def _client_returning(*series: Datapoints) -> MagicMock:
    raw = MagicMock(spec=DatapointsList)
    raw.__getitem__.side_effect = lambda idx: series[idx]
    client = MagicMock()
    client.time_series.data.retrieve.return_value = raw
    return client


def _base_ms() -> int:
    return int(_START.timestamp() * 1000)


# ---------------------------------------------------------------------------
# _build_requests
# ---------------------------------------------------------------------------


def test_aggregate_without_granularity_raises_value_error() -> None:
    retriever = DatapointsRetriever(MagicMock())
    param = _param("A", aggregate="average")

    with pytest.raises(ValueError, match="Missing granularity for 'A'"):
        retriever.retrieve_datapoints([param], _START, _END)


def test_same_timeseries_and_granularity_with_different_aggregates_are_merged() -> None:
    retriever = DatapointsRetriever(MagicMock())
    avg = _param("A", aggregate="average", granularity="1h")
    total = _param("B", aggregate="sum", granularity="1h")

    requests, index_mapping = retriever._build_requests([avg, total], _START, _END)

    assert len(requests) == 1
    assert requests[0].aggregates == ["average", "sum"]
    assert index_mapping == {0: 0, 1: 0}


def test_repeated_aggregate_on_same_series_is_not_duplicated() -> None:
    retriever = DatapointsRetriever(MagicMock())
    first = _param("A", aggregate="average", granularity="1h")
    second = _param("B", aggregate="average", granularity="1h")

    requests, _ = retriever._build_requests([first, second], _START, _END)

    assert requests[0].aggregates == ["average"]


def test_same_timeseries_different_granularity_produces_separate_requests() -> None:
    retriever = DatapointsRetriever(MagicMock())
    hourly = _param("A", aggregate="average", granularity="1h")
    daily = _param("B", aggregate="average", granularity="1d")

    requests, index_mapping = retriever._build_requests([hourly, daily], _START, _END)

    assert len(requests) == 2
    assert index_mapping == {0: 0, 1: 1}


def test_raw_and_aggregate_for_same_series_are_distinct_requests() -> None:
    retriever = DatapointsRetriever(MagicMock())
    raw_param = _param("A")
    agg_param = _param("B", aggregate="average", granularity="1h")

    requests, index_mapping = retriever._build_requests(
        [raw_param, agg_param], _START, _END
    )

    assert len(requests) == 2
    assert requests[0].granularity is None
    assert requests[1].granularity == "1h"


# ---------------------------------------------------------------------------
# retrieve_datapoints + _parse_datapoints
# ---------------------------------------------------------------------------


def test_merged_aggregates_pull_their_own_column_per_parameter() -> None:
    base = _base_ms()
    dp = _datapoints(
        timestamps=[base, base + 60_000],
        average=[10.0, 20.0],
        sum=[100.0, 200.0],
    )
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    avg = _param("A", aggregate="average", granularity="1h")
    total = _param("B", aggregate="sum", granularity="1h")

    result = retriever.retrieve_datapoints([avg, total], _START, _END)

    assert [value for _, value in result[0]] == [10.0, 20.0]
    assert [value for _, value in result[1]] == [100.0, 200.0]


def test_parse_datapoints_drops_none_values_and_aligns_timestamps() -> None:
    base = _base_ms()
    dp = _datapoints(
        timestamps=[base, base + 60_000, base + 120_000],
        value=[1.0, None, 3.0],  # type: ignore[list-item]
    )
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    result = retriever.retrieve_datapoints([_param("A")], _START, _END)

    assert [value for _, value in result[0]] == [1.0, 3.0]
    first_ts = result[0][0][0]
    assert first_ts == datetime.fromtimestamp(base / 1000, tz=UTC)


def test_missing_column_is_treated_as_empty_series() -> None:
    dp = _datapoints(timestamps=[], value=None)
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    result = retriever.retrieve_datapoints([_param("A")], _START, _END)

    assert result == [[]]


def test_non_numeric_datapoints_type_is_rejected() -> None:
    dp = _datapoints(timestamps=[_base_ms()], value=None, dp_type="string")
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    with pytest.raises(ValueError, match="expected numeric datapoints"):
        retriever.retrieve_datapoints([_param("A")], _START, _END)


def test_missing_aggregate_column_is_treated_as_empty_series() -> None:
    # The requested aggregate column is absent (``None``) on the response, e.g.
    # a series with no data in the window; it should yield an empty series
    # rather than raising.
    dp = _datapoints(timestamps=[], average=None)  # type: ignore[arg-type]
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    param = _param("A", aggregate="average", granularity="1h")
    result = retriever.retrieve_datapoints([param], _START, _END)

    assert result == [[]]
