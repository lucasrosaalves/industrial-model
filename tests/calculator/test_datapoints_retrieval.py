from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from cognite.client.data_classes.datapoints import Datapoints, DatapointsQuery

from industrial_model.calculator import datapoints_retrieval
from industrial_model.calculator.datapoints_retrieval import (
    DatapointsRetriever,
    _min_page_sizes,
)
from industrial_model.calculator.exceptions import (
    CalculatorError,
    DatapointsRetrievalError,
)
from industrial_model.calculator.models import (
    MultiTimeSeriesParameter,
    ReducerType,
    Series,
    TimeSeriesParameter,
    TimeSeriesParameterBase,
)
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
) -> TimeSeriesParameter:
    return TimeSeriesParameter(
        alias=alias,
        timeseries_instance_id=InstanceId(space=space, external_id=external_id),
        aggregate_type=aggregate,  # type: ignore[arg-type]
        granularity=granularity,
    )


def _multi_param(
    alias: str,
    instances: list[tuple[str, str]],
    reducer: ReducerType,
    *,
    aggregate: str | None = None,
    granularity: str | None = None,
) -> MultiTimeSeriesParameter:
    return MultiTimeSeriesParameter(
        alias=alias,
        timeseries_instance_ids=[
            InstanceId(space=space, external_id=external_id)
            for space, external_id in instances
        ],
        aggregate_type=aggregate,  # type: ignore[arg-type]
        granularity=granularity,
        reducer=reducer,
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
    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(return_value=list(series))
    return client


def _retrieve(
    retriever: DatapointsRetriever,
    parameters: Sequence[TimeSeriesParameterBase],
    start: datetime = _START,
    end: datetime = _END,
    timezone: str | None = None,
) -> list[list[Series]]:
    return asyncio.run(
        retriever.retrieve_datapoints(parameters, start, end, timezone=timezone)
    )


def _base_ms() -> int:
    return int(_START.timestamp() * 1000)


# ---------------------------------------------------------------------------
# _build_requests
# ---------------------------------------------------------------------------


def test_same_timeseries_and_granularity_with_different_aggregates_are_merged() -> None:
    retriever = DatapointsRetriever(MagicMock())
    avg = _param("A", aggregate="average", granularity="1h")
    total = _param("B", aggregate="sum", granularity="1h")

    requests, index_mapping = retriever._build_requests([avg, total], _START, _END)

    assert len(requests) == 1
    assert requests[0].aggregates == ["average", "sum"]
    assert index_mapping == [[0], [0]]


def test_repeated_aggregate_on_same_series_is_not_duplicated() -> None:
    retriever = DatapointsRetriever(MagicMock())
    first = _param("A", aggregate="average", granularity="1h")
    second = _param("B", aggregate="average", granularity="1h")

    requests, _ = retriever._build_requests([first, second], _START, _END)

    assert requests[0].aggregates == ["average"]


def test_retrieve_timezone_is_set_on_every_aggregate_query() -> None:
    retriever = DatapointsRetriever(MagicMock())
    hourly = _param("A", aggregate="average", granularity="1h")
    daily = _param("B", aggregate="sum", granularity="1d")

    requests, _ = retriever._build_requests(
        [hourly, daily], _START, _END, timezone="America/New_York"
    )

    assert [request.timezone for request in requests] == [
        "America/New_York",
        "America/New_York",
    ]


def test_retrieve_timezone_is_applied_when_calling_cdf() -> None:
    dp = _datapoints(timestamps=[_base_ms()], average=[1.0])
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)
    daily = _param("A", aggregate="average", granularity="1d")

    _retrieve(retriever, [daily], timezone="America/New_York")

    query = client.time_series.data.retrieve.call_args.kwargs["instance_id"][0]
    assert query.timezone == "America/New_York"
    assert query.granularity == "1d"


def test_raw_retrieve_does_not_set_timezone() -> None:
    retriever = DatapointsRetriever(MagicMock())
    raw = _param("A")

    requests, _ = retriever._build_requests(
        [raw], _START, _END, timezone="America/New_York"
    )

    assert requests[0].granularity is None
    assert "timezone" not in requests[0].dump()


def test_mixed_raw_and_aggregate_only_sets_timezone_on_aggregates() -> None:
    retriever = DatapointsRetriever(MagicMock())
    raw = _param("A")
    daily = _param("B", aggregate="sum", granularity="1d")

    requests, _ = retriever._build_requests(
        [raw, daily], _START, _END, timezone="America/New_York"
    )

    assert "timezone" not in requests[0].dump()
    assert requests[1].timezone == "America/New_York"


def test_merged_aggregates_keep_a_single_timezone() -> None:
    retriever = DatapointsRetriever(MagicMock())
    avg = _param("A", aggregate="average", granularity="1h")
    total = _param("B", aggregate="sum", granularity="1h")

    requests, _ = retriever._build_requests(
        [avg, total], _START, _END, timezone="Europe/Oslo"
    )

    assert len(requests) == 1
    assert requests[0].aggregates == ["average", "sum"]
    assert requests[0].timezone == "Europe/Oslo"


def test_same_timeseries_different_granularity_produces_separate_requests() -> None:
    retriever = DatapointsRetriever(MagicMock())
    hourly = _param("A", aggregate="average", granularity="1h")
    daily = _param("B", aggregate="average", granularity="1d")

    requests, index_mapping = retriever._build_requests([hourly, daily], _START, _END)

    assert len(requests) == 2
    assert index_mapping == [[0], [1]]


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

    result = _retrieve(retriever, [avg, total], _START, _END)

    assert [value for _, value in result[0][0]] == [10.0, 20.0]
    assert [value for _, value in result[1][0]] == [100.0, 200.0]


def test_parse_datapoints_drops_none_values_and_aligns_timestamps() -> None:
    base = _base_ms()
    dp = _datapoints(
        timestamps=[base, base + 60_000, base + 120_000],
        value=[1.0, None, 3.0],  # type: ignore[list-item]
    )
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    result = _retrieve(retriever, [_param("A")], _START, _END)

    assert [value for _, value in result[0][0]] == [1.0, 3.0]
    first_ts = result[0][0][0][0]
    assert first_ts == datetime.fromtimestamp(base / 1000, tz=UTC)


def test_missing_column_is_treated_as_empty_series() -> None:
    dp = _datapoints(timestamps=[], value=None)
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    result = _retrieve(retriever, [_param("A")], _START, _END)

    assert result == [[[]]]


def test_non_numeric_datapoints_type_is_rejected() -> None:
    dp = _datapoints(timestamps=[_base_ms()], value=None, dp_type="string")
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    with pytest.raises(DatapointsRetrievalError, match="expected numeric datapoints"):
        _retrieve(retriever, [_param("A")], _START, _END)


def test_every_timeseries_goes_into_one_sdk_retrieve() -> None:
    # More than 100 series is the SDK's job to split into requests; issuing
    # several concurrent ``retrieve`` calls ourselves is what triggers the
    # SDK's silent first-page-only result.
    base = _base_ms()
    params = [_param(f"P{i}", external_id=f"ts-{i}") for i in range(150)]
    series = [
        _datapoints(external_id=f"ts-{i}", timestamps=[base], value=[float(i)])
        for i in range(150)
    ]
    client = _client_returning(*series)

    retriever = DatapointsRetriever(client)
    result = _retrieve(retriever, params, _START, _END)

    assert client.time_series.data.retrieve.call_count == 1
    requests = client.time_series.data.retrieve.call_args.kwargs["instance_id"]
    assert len(requests) == 150
    assert [value for _, value in result[0][0]] == [0.0]
    assert [value for _, value in result[149][0]] == [149.0]


def test_single_instance_id_param_returns_one_leaf_series() -> None:
    dp = _datapoints(timestamps=[_base_ms()], value=[1.0])
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    result = _retrieve(retriever, [_param("A")], _START, _END)

    assert len(result[0]) == 1
    assert [value for _, value in result[0][0]] == [1.0]


def test_multi_instance_param_requests_one_series_per_instance() -> None:
    retriever = DatapointsRetriever(MagicMock())
    param = _multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )

    requests, index_mapping = retriever._build_requests([param], _START, _END)

    assert len(requests) == 2
    assert index_mapping == [[0, 1]]


def test_multi_instance_param_returns_each_leaf_series_unreduced() -> None:
    # DatapointsRetriever only fetches and parses data - combining a
    # parameter's series (via its reducer) is the caller's responsibility.
    base = _base_ms()
    dp1 = _datapoints(
        external_id="ts1", timestamps=[base, base + 60_000], average=[1.0, 2.0]
    )
    dp2 = _datapoints(
        external_id="ts2", timestamps=[base, base + 60_000], average=[10.0, 20.0]
    )
    client = _client_returning(dp1, dp2)
    retriever = DatapointsRetriever(client)

    param = _multi_param(
        "A",
        [("s", "ts1"), ("s", "ts2")],
        reducer="sum",
        aggregate="average",
        granularity="1h",
    )
    result = _retrieve(retriever, [param], _START, _END)

    assert len(result) == 1
    assert len(result[0]) == 2  # one leaf series per instance id, not reduced
    assert [value for _, value in result[0][0]] == [1.0, 2.0]
    assert [value for _, value in result[0][1]] == [10.0, 20.0]


def test_shared_instance_id_across_parameters_reuses_one_request() -> None:
    retriever = DatapointsRetriever(MagicMock())
    first = _param("A", external_id="ts1", aggregate="average", granularity="1h")
    second = _param("B", external_id="ts1", aggregate="average", granularity="1h")

    requests, index_mapping = retriever._build_requests([first, second], _START, _END)

    assert len(requests) == 1
    assert index_mapping == [[0], [0]]


def test_shared_instance_id_across_parameters_yields_the_same_leaf_series() -> None:
    base = _base_ms()
    dp = _datapoints(external_id="ts1", timestamps=[base], average=[5.0])
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    first = _param("A", external_id="ts1", aggregate="average", granularity="1h")
    second = _param("B", external_id="ts1", aggregate="average", granularity="1h")
    result = _retrieve(retriever, [first, second], _START, _END)

    expected = [(datetime.fromtimestamp(base / 1000, tz=UTC), 5.0)]
    assert result[0][0] == result[1][0] == expected


def test_mixed_raw_and_multi_instance_aggregate_params_in_one_batch() -> None:
    base = _base_ms()
    raw_dp = _datapoints(external_id="raw_ts", timestamps=[base], value=[1.0])
    agg_dp1 = _datapoints(external_id="agg_ts1", timestamps=[base], average=[2.0])
    agg_dp2 = _datapoints(external_id="agg_ts2", timestamps=[base], average=[3.0])
    client = _client_returning(raw_dp, agg_dp1, agg_dp2)
    retriever = DatapointsRetriever(client)

    raw_param = _param("A", external_id="raw_ts")
    multi_param = _multi_param(
        "B",
        [("s", "agg_ts1"), ("s", "agg_ts2")],
        reducer="max",
        aggregate="average",
        granularity="1h",
    )

    result = _retrieve(retriever, [raw_param, multi_param], _START, _END)

    assert len(result) == 2
    assert len(result[0]) == 1  # raw_param: one leaf series
    assert len(result[1]) == 2  # multi_param: two leaf series, unreduced
    assert [value for _, value in result[0][0]] == [1.0]
    assert [value for _, value in result[1][0]] == [2.0]
    assert [value for _, value in result[1][1]] == [3.0]


def test_retrieve_datapoints_preserves_parameter_order() -> None:
    base = _base_ms()
    dp_a = _datapoints(external_id="a", timestamps=[base], value=[1.0])
    dp_b = _datapoints(external_id="b", timestamps=[base], value=[2.0])
    dp_c = _datapoints(external_id="c", timestamps=[base], value=[3.0])
    client = _client_returning(dp_a, dp_b, dp_c)
    retriever = DatapointsRetriever(client)

    params = [
        _param("A", external_id="a"),
        _param("B", external_id="b"),
        _param("C", external_id="c"),
    ]
    result = _retrieve(retriever, params, _START, _END)

    assert [value for _, value in result[0][0]] == [1.0]
    assert [value for _, value in result[1][0]] == [2.0]
    assert [value for _, value in result[2][0]] == [3.0]


def test_missing_aggregate_column_is_treated_as_empty_series() -> None:
    # The requested aggregate column is absent (``None``) on the response, e.g.
    # a series with no data in the window; it should yield an empty series
    # rather than raising.
    dp = _datapoints(timestamps=[], average=None)  # type: ignore[arg-type]
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    param = _param("A", aggregate="average", granularity="1h")
    result = _retrieve(retriever, [param], _START, _END)

    assert result == [[[]]]


def test_short_cdf_response_is_rejected() -> None:
    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(
        return_value=[
            _datapoints(external_id="ts1", timestamps=[_base_ms()], value=[1.0])
        ]
    )
    retriever = DatapointsRetriever(client)
    params = [_param("A", external_id="ts1"), _param("B", external_id="ts2")]

    with pytest.raises(
        DatapointsRetrievalError, match="expected 2 datapoint series from CDF, got 1"
    ):
        _retrieve(retriever, params, _START, _END)


def test_timestamp_and_value_length_mismatch_raises() -> None:
    dp = _datapoints(timestamps=[_base_ms(), _base_ms() + 60_000], value=[1.0])
    client = _client_returning(dp)
    retriever = DatapointsRetriever(client)

    with pytest.raises(
        DatapointsRetrievalError,
        match="CDF returned 2 timestamp\\(s\\) but 1 'value' value\\(s\\) for 'A'",
    ):
        _retrieve(retriever, [_param("A")], _START, _END)


# ---------------------------------------------------------------------------
# A full first page is asked for again, in case the SDK stopped there.
# ---------------------------------------------------------------------------

# With the read concurrency pinned to 5 (see the fixture below) the SDK asks a
# lone series for its whole budget on the first page. The mocks below cut
# there and stop, like the SDK does when its request scheduler starves.
_READ = 5
_PAGE = 10_000
_RAW_PAGE = 100_000
_HOUR_MS = 3_600_000


@pytest.fixture(autouse=True)
def _pin_read_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SDK freezes its concurrency settings after the first real request,
    # so patch the lookup rather than the setting itself.
    monkeypatch.setattr(datapoints_retrieval, "_read_concurrency", lambda: _READ)


def _limited_pages(
    timestamps: list[int],
    *,
    aggregate: str | None,
    page_size: int,
) -> MagicMock:
    async def retrieve(*, instance_id: list[object], **_: object) -> list[Datapoints]:
        pages: list[Datapoints] = []
        for query in instance_id:
            start = query.start  # type: ignore[attr-defined]
            end = query.end  # type: ignore[attr-defined]
            start_ms = (
                start if isinstance(start, int) else int(start.timestamp() * 1000)
            )
            end_ms = end if isinstance(end, int) else int(end.timestamp() * 1000)
            selected = [ts for ts in timestamps if start_ms <= ts < end_ms][:page_size]
            if aggregate is None:
                dp = _datapoints(
                    timestamps=selected, value=[float(ts) for ts in selected]
                )
            else:
                dp = _datapoints(timestamps=selected)
                setattr(dp, aggregate, [float(ts) for ts in selected])
            pages.append(dp)
        return pages

    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(side_effect=retrieve)
    return client


def _end_after(timestamps: list[int]) -> datetime:
    return datetime.fromtimestamp((timestamps[-1] + _HOUR_MS) / 1000, UTC)


def _result_ms(series: Series) -> list[int]:
    return [int(ts.timestamp() * 1000) for ts, _ in series]


def test_min_page_sizes_follow_the_sdk_request_plan() -> None:
    def agg(i: int) -> DatapointsQuery:
        return DatapointsQuery(
            instance_id=("s", f"a{i}"), aggregates=["average"], granularity="1h"
        )

    def raw(i: int) -> DatapointsQuery:
        return DatapointsQuery(instance_id=("s", f"r{i}"))

    # Eager path: every series gets the whole budget.
    assert _min_page_sizes([agg(0), raw(0)]) == (_PAGE, _RAW_PAGE)
    # 100 aggregates over read=5 requests: 20 per request.
    assert _min_page_sizes([agg(i) for i in range(100)]) == (500, _RAW_PAGE)
    # 594 aggregates need ceil(594 / 100) = 6 requests: 99 per request.
    assert _min_page_sizes([agg(i) for i in range(594)]) == (101, _RAW_PAGE)
    # Raw and aggregate are split independently.
    mixed = [agg(i) for i in range(10)] + [raw(i) for i in range(50)]
    assert _min_page_sizes(mixed) == (5_000, 10_000)


@pytest.mark.parametrize(
    ("aggregate", "granularity", "timezone"),
    [
        ("average", "1m", None),
        ("average", "1h", None),
        ("average", "1h", "America/Denver"),
        ("average", "1d", "America/Denver"),
        ("average", "1mo", None),
        ("average", "1q", None),
        ("average", "1y", None),
    ],
)
def test_full_aggregate_page_is_followed_from_its_last_point(
    aggregate: str, granularity: str, timezone: str | None
) -> None:
    timestamps = [_base_ms() + i * _HOUR_MS for i in range(_PAGE + 5)]
    client = _limited_pages(timestamps, aggregate=aggregate, page_size=_PAGE)
    retriever = DatapointsRetriever(client)
    param = _param("A", aggregate=aggregate, granularity=granularity)

    result = _retrieve(
        retriever, [param], _START, _end_after(timestamps), timezone=timezone
    )

    assert client.time_series.data.retrieve.call_count == 2
    assert _result_ms(result[0][0]) == timestamps
    second_start = (
        client.time_series.data.retrieve.call_args_list[1]
        .kwargs["instance_id"][0]
        .start
    )
    second_ms = (
        second_start
        if isinstance(second_start, int)
        else int(second_start.timestamp() * 1000)
    )
    assert timestamps[_PAGE - 1] < second_ms <= timestamps[_PAGE]


def test_full_raw_page_is_followed_from_its_last_point() -> None:
    timestamps = [_base_ms() + i * 1_000 for i in range(_RAW_PAGE + 5)]
    client = _limited_pages(timestamps, aggregate=None, page_size=_RAW_PAGE)
    retriever = DatapointsRetriever(client)

    result = _retrieve(retriever, [_param("A")], _START, _end_after(timestamps))

    assert client.time_series.data.retrieve.call_count == 2
    assert _result_ms(result[0][0]) == timestamps


@pytest.mark.parametrize(
    ("aggregate", "granularity", "count"),
    [(None, None, _RAW_PAGE - 1), ("average", "1h", _PAGE - 1)],
)
def test_page_shorter_than_the_sdk_first_limit_is_taken_as_complete(
    aggregate: str | None, granularity: str | None, count: int
) -> None:
    timestamps = [_base_ms() + i * 1_000 for i in range(count)]
    client = _limited_pages(timestamps, aggregate=aggregate, page_size=count)
    retriever = DatapointsRetriever(client)
    param = _param("A", aggregate=aggregate, granularity=granularity)

    result = _retrieve(retriever, [param], _START, _end_after(timestamps))

    assert client.time_series.data.retrieve.call_count == 1
    assert _result_ms(result[0][0]) == timestamps


def test_page_ending_exactly_on_the_budget_is_checked_once_more() -> None:
    # A page as long as the SDK's minimum may be full, so one more request
    # goes out; it comes back empty and the series is closed without
    # duplicates.
    timestamps = [_base_ms() + i * _HOUR_MS for i in range(_PAGE)]
    client = _limited_pages(timestamps, aggregate="average", page_size=_PAGE)
    retriever = DatapointsRetriever(client)
    param = _param("A", aggregate="average", granularity="1h")

    result = _retrieve(
        retriever, [param], _START, _end_after(timestamps), timezone="America/Denver"
    )

    assert client.time_series.data.retrieve.call_count == 2
    assert _result_ms(result[0][0]) == timestamps


def test_naive_start_and_end_are_sent_as_utc() -> None:
    client = _limited_pages([_base_ms()], aggregate="average", page_size=_PAGE)
    retriever = DatapointsRetriever(client)
    param = _param("A", aggregate="average", granularity="1h")

    _retrieve(
        retriever,
        [param],
        _START.replace(tzinfo=None),
        _END.replace(tzinfo=None),
        timezone="America/Denver",
    )

    query = client.time_series.data.retrieve.call_args.kwargs["instance_id"][0]
    assert query.start == _START
    assert query.end == _END
    assert query.start.tzinfo is not None


def test_first_page_floor_shrinks_with_more_series_and_short_ones_drop_out() -> None:
    # 100 aggregate series over read=5 requests: the SDK hands each at most
    # 500 points on the first page, so a 500-point page is followed while a
    # 10-point series is complete and leaves the batch.
    count = 501
    page = 500
    timestamps = [_base_ms() + i * _HOUR_MS for i in range(count)]
    short_id = "short"

    async def retrieve(*, instance_id: list[object], **_: object) -> list[Datapoints]:
        pages: list[Datapoints] = []
        for query in instance_id:
            start = query.start  # type: ignore[attr-defined]
            stop = query.end  # type: ignore[attr-defined]
            start_ms = (
                start if isinstance(start, int) else int(start.timestamp() * 1000)
            )
            end_ms = stop if isinstance(stop, int) else int(stop.timestamp() * 1000)
            dumped = query.dump()  # type: ignore[attr-defined]
            external_id = dumped["instance_id"]["external_id"]
            available = timestamps[:10] if external_id == short_id else timestamps
            selected = [ts for ts in available if start_ms <= ts < end_ms][:page]
            pages.append(
                _datapoints(
                    external_id=external_id,
                    timestamps=selected,
                    average=[float(ts) for ts in selected],
                )
            )
        return pages

    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(side_effect=retrieve)
    params = [
        _param(f"P{i}", external_id=f"ts-{i}", aggregate="average", granularity="1h")
        for i in range(99)
    ]
    params.append(
        _param("S", external_id=short_id, aggregate="average", granularity="1h")
    )

    result = _retrieve(
        DatapointsRetriever(client),
        params,
        _START,
        _end_after(timestamps),
        timezone="America/Denver",
    )

    assert client.time_series.data.retrieve.call_count == 2
    second_batch = client.time_series.data.retrieve.call_args_list[1].kwargs[
        "instance_id"
    ]
    assert len(second_batch) == 99
    assert all(
        query.dump()["instance_id"]["external_id"] != short_id for query in second_batch
    )
    for series in result[:-1]:
        got = _result_ms(series[0])
        assert got == timestamps
        assert got.count(timestamps[page - 1]) == 1
    assert _result_ms(result[-1][0]) == timestamps[:10]


def test_paged_aggregate_keeps_every_merged_column() -> None:
    timestamps = [_base_ms() + i * _HOUR_MS for i in range(_PAGE + 3)]

    async def retrieve(*, instance_id: list[object], **_: object) -> list[Datapoints]:
        query = instance_id[0]
        start = query.start  # type: ignore[attr-defined]
        stop = query.end  # type: ignore[attr-defined]
        start_ms = start if isinstance(start, int) else int(start.timestamp() * 1000)
        end_ms = stop if isinstance(stop, int) else int(stop.timestamp() * 1000)
        selected = [ts for ts in timestamps if start_ms <= ts < end_ms][:_PAGE]
        return [
            _datapoints(
                timestamps=selected,
                average=[float(ts) for ts in selected],
                sum=[float(ts) / 10 for ts in selected],
            )
        ]

    client = MagicMock()
    client.time_series.data.retrieve = AsyncMock(side_effect=retrieve)
    retriever = DatapointsRetriever(client)
    average = _param("A", aggregate="average", granularity="1h")
    total = _param("B", aggregate="sum", granularity="1h")

    result = _retrieve(
        retriever,
        [average, total],
        _START,
        _end_after(timestamps),
        timezone="America/Denver",
    )

    assert _result_ms(result[0][0]) == timestamps
    assert _result_ms(result[1][0]) == timestamps
    assert [value for _, value in result[0][0]] == [float(ts) for ts in timestamps]
    assert [value for _, value in result[1][0]] == [ts / 10 for ts in timestamps]
    assert len({ts for ts, _ in result[0][0]}) == len(timestamps)


def test_every_retriever_error_is_catchable_as_calculator_error() -> None:
    dp = _datapoints(timestamps=[_base_ms()], value=None, dp_type="string")
    retriever = DatapointsRetriever(_client_returning(dp))

    with pytest.raises(CalculatorError):
        _retrieve(retriever, [_param("A")], _START, _END)
