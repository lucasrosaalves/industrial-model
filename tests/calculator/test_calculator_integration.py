"""End-to-end Calculator test against a real Cognite Data Fusion project.

Unlike every other test in ``tests/calculator/``, this one makes no use of
mocks: it creates a throwaway data-modeling space, provisions real
``CogniteTimeSeries`` instances in it, writes real datapoints, then drives
them through ``Calculator`` with formulas covering constants, single and
multi time series, every reducer, aggregates, and known edge cases (a
timestamp gap, mismatched series lengths, an empty series, a window with
no data, and formula-level intersection of a reduced parameter with a
gapped sibling).

Every test here must justify itself by checking something a mock cannot:
an assumption about the real Cognite API that our fixtures would otherwise
just assert back at us. Pure in-process logic belongs in the unit tests.
The assumptions currently pinned down are that CDF omits aggregate buckets
with no underlying data (what ``SeriesReducer``'s timestamp intersection
relies on), that CDF's hourly ``average`` is time-weighted rather than a
simple mean of samples, that a merged multi-aggregate request really does
populate every requested column over one shared timestamp axis, that
responses come back in request order even when split across chunks (what
``_build_requests``' positional index mapping relies on), and that two
series with data in the same hours land on identical bucket timestamps
(what makes ``strict`` alignment usable at all).

Requires live CDF credentials, like the other ``integration``-marked tests in
this repo (see ``tests/hubs.py``): excluded from ``scripts/test-unit.sh`` /
PR CI, but included in ``scripts/test-integration.sh``, which runs in CD. To
run it locally:

    uv run pytest tests/calculator/test_calculator_integration.py -m integration

It uses the same ``.env`` / ``tests/cognite-sdk-config.yaml`` CDF_* variables
as those tests. The target project must have Data Modeling enabled with the
standard Cognite Core Data Model (``cdf_cdm``) present, which is true of
essentially all modern CDF projects - that's what backs
``CogniteTimeSeriesApply`` below.

Every space/timeseries created here is scoped to a fresh, randomly-named
space per run and torn down in the ``dataset`` fixture, so re-running this
file repeatedly against the same project is safe.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cognite.client import CogniteClient
from cognite.client.data_classes.data_modeling import SpaceApply
from cognite.client.data_classes.data_modeling.cdm.v1 import CogniteTimeSeriesApply
from cognite.client.data_classes.data_modeling.ids import NodeId
from dotenv import load_dotenv

from industrial_model.calculator import (
    CalculationResult,
    Calculator,
    CalculatorQuery,
    ConstantParameter,
    MultiTimeSeriesParameter,
    ReducerType,
    TimeSeriesParameter,
    datapoints_retrieval,
)
from industrial_model.calculator.formula_expression.exceptions import (
    ParameterTimestampError,
)
from industrial_model.engines._internal import generate_engine_params
from industrial_model.models import InstanceId

pytestmark = pytest.mark.integration

# A fixed historical anchor (rather than "now") keeps every hourly bucket
# below fully in the past, so there's no risk of asserting on an
# in-progress, not-yet-complete aggregate bucket.
_BASE = datetime(2020, 1, 1, tzinfo=UTC)
_WINDOW_START = _BASE
_WINDOW_END = _BASE + timedelta(hours=3)

_TIME_SERIES_NAMES = [
    "produced",
    "scrap",
    "short",
    "temp",
    "line_1",
    "line_2",
    "line_3",
    "gap_a",
    "gap_b",
    "empty",
]


@dataclass
class _Dataset:
    space: str
    produced: InstanceId
    scrap: InstanceId
    short: InstanceId
    temp: InstanceId
    line_1: InstanceId
    line_2: InstanceId
    line_3: InstanceId
    gap_a: InstanceId
    gap_b: InstanceId
    empty: InstanceId


@pytest.fixture(scope="module")
def client() -> CogniteClient:
    load_dotenv(override=True)
    config_path = Path(os.path.dirname(__file__)).parent / "cognite-sdk-config.yaml"
    cognite_client, _ = generate_engine_params(config_path)
    return cognite_client


@pytest.fixture(scope="module")
def calculator(client: CogniteClient) -> Calculator:
    return Calculator(client)


def _calculate(
    calculator: Calculator,
    query: CalculatorQuery,
    start: datetime,
    end: datetime,
) -> CalculationResult:
    return asyncio.run(calculator.calculate(query, start, end))


def _calculate_multiples(
    calculator: Calculator,
    queries: list[CalculatorQuery],
    start: datetime,
    end: datetime,
) -> list[CalculationResult]:
    return asyncio.run(calculator.calculate_multiples(queries, start, end))


@pytest.fixture(scope="module")
def dataset(client: CogniteClient) -> Iterator[_Dataset]:
    space = f"calc-int-test-{uuid.uuid4().hex[:10]}"
    client.data_modeling.spaces.apply(
        SpaceApply(
            space=space,
            name="Calculator integration test (safe to delete)",
            description="Throwaway space created by test_calculator_integration.py",
        )
    )

    client.data_modeling.instances.apply(
        nodes=[
            CogniteTimeSeriesApply(
                space=space,
                external_id=name,
                is_step=False,
                time_series_type="numeric",
            )
            for name in _TIME_SERIES_NAMES
        ]
    )

    def _insert(name: str, points: list[tuple[datetime, float]]) -> None:
        client.time_series.data.insert(points, instance_id=NodeId(space, name))

    # Raw series for plain arithmetic and guarded-division scenarios.
    # scrap includes a real zero to exercise the division guard.
    _insert(
        "produced",
        list(
            zip(
                (_BASE + timedelta(minutes=i) for i in range(5)),
                [100.0, 110.0, 120.0, 130.0, 140.0],
                strict=True,
            )
        ),
    )
    _insert(
        "scrap",
        list(
            zip(
                (_BASE + timedelta(minutes=i) for i in range(5)),
                [10.0, 0.0, 5.0, 20.0, 2.0],
                strict=True,
            )
        ),
    )
    # Fewer points than produced/scrap - used to probe default timestamp
    # intersection (overlap kept) vs strict alignment (mismatch raises).
    _insert(
        "short",
        list(
            zip(
                (_BASE + timedelta(minutes=i) for i in range(3)),
                [1.0, 2.0, 3.0],
                strict=True,
            )
        ),
    )

    # Hourly buckets for the average-aggregate probe. CDF's "average" is
    # time-weighted over the full bucket (including interpolation across
    # unsampled edges), so tests must not assume the naive 50.0 / 70.0
    # mean of the sampled points - see test_single_aggregate_hourly_average.
    _insert(
        "temp",
        [(_BASE + timedelta(minutes=m), 50.0) for m in (5, 20, 35, 50)]
        + [(_BASE + timedelta(minutes=60 + m), 70.0) for m in (5, 20, 35, 50)],
    )

    # Exactly one raw point per hourly bucket per line, so the "sum"
    # aggregate for that bucket is just that single value - makes the
    # combined reducer math trivial to predict by hand.
    _insert(
        "line_1",
        [
            (_BASE + timedelta(minutes=15), 100.0),
            (_BASE + timedelta(minutes=75), 110.0),
        ],
    )
    _insert(
        "line_2",
        [
            (_BASE + timedelta(minutes=15), 200.0),
            (_BASE + timedelta(minutes=75), 210.0),
        ],
    )
    _insert(
        "line_3",
        [
            (_BASE + timedelta(minutes=15), 300.0),
            (_BASE + timedelta(minutes=75), 310.0),
        ],
    )

    # gap_b has no data at all in hour 1's window - the key probe for
    # whether CDF's aggregate API omits empty buckets (as SeriesReducer
    # assumes) rather than returning a null/zero datapoint for them.
    _insert(
        "gap_a",
        [(_BASE + timedelta(minutes=15), 5.0), (_BASE + timedelta(minutes=75), 6.0)],
    )
    _insert("gap_b", [(_BASE + timedelta(minutes=75), 50.0)])
    # Provisioned but never written to - probes that a real CDF retrieve
    # of an empty numeric series is an empty result, not an error.

    try:
        yield _Dataset(
            space=space,
            **{
                name: InstanceId(space=space, external_id=name)
                for name in _TIME_SERIES_NAMES
            },
        )
    finally:
        client.data_modeling.instances.delete(
            nodes=[NodeId(space, name) for name in _TIME_SERIES_NAMES]
        )
        client.data_modeling.spaces.delete([space])


# ---------------------------------------------------------------------------
# Raw single time series
# ---------------------------------------------------------------------------


def test_simple_raw_arithmetic(calculator: Calculator, dataset: _Dataset) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} - {SCRAP}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="SCRAP", timeseries_instance_id=dataset.scrap),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx(
        [90.0, 110.0, 115.0, 110.0, 138.0]
    )
    assert all(dp.timestamp.utcoffset() == timedelta(0) for dp in result.datapoints)


def test_guarded_division_handles_a_real_zero_denominator(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} / {SCRAP} if {SCRAP} != 0 else -1",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="SCRAP", timeseries_instance_id=dataset.scrap),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx(
        [10.0, -1.0, 24.0, 6.5, 70.0]
    )


def test_mismatched_series_are_intersected_by_default(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} + {SHORT}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="SHORT", timeseries_instance_id=dataset.short),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx(
        [101.0, 112.0, 123.0]
    )


def test_strict_alignment_raises_when_series_timestamps_differ(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} + {SHORT}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="SHORT", timeseries_instance_id=dataset.short),
        ],
        alignment="strict",
    )

    with pytest.raises(ParameterTimestampError):
        _calculate(calculator, query, _WINDOW_START, _WINDOW_END)


def test_strict_alignment_accepts_identically_bucketed_aggregates(
    calculator: Calculator, dataset: _Dataset
) -> None:
    """The premise behind offering ``strict`` at all.

    Two series with raw data in the same hours must come back on byte-for-byte
    identical bucket timestamps, or ``strict`` would be unusable in practice
    even for well-behaved data. Only the failure path is covered above.
    """
    query = CalculatorQuery(
        formula="{L1} + {L2}",
        parameters=[
            TimeSeriesParameter(
                alias="L1",
                timeseries_instance_id=dataset.line_1,
                aggregate_type="sum",
                granularity="1h",
            ),
            TimeSeriesParameter(
                alias="L2",
                timeseries_instance_id=dataset.line_2,
                aggregate_type="sum",
                granularity="1h",
            ),
        ],
        alignment="strict",
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx([300.0, 320.0])


def test_timeseries_with_no_datapoints_returns_empty_result(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{EMPTY}",
        parameters=[
            TimeSeriesParameter(alias="EMPTY", timeseries_instance_id=dataset.empty)
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert result.datapoints == []


def test_intersect_with_an_empty_series_is_empty(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} + {EMPTY}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="EMPTY", timeseries_instance_id=dataset.empty),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert result.datapoints == []


def test_window_with_no_data_returns_empty_result(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            )
        ],
    )
    start = _BASE - timedelta(days=30)
    end = start + timedelta(hours=3)

    result = _calculate(calculator, query, start, end)

    assert result.datapoints == []


# ---------------------------------------------------------------------------
# Aggregates and constants
# ---------------------------------------------------------------------------


def test_single_aggregate_hourly_average(
    calculator: Calculator, dataset: _Dataset
) -> None:
    # Gap found by running this suite for real: CDF's "average" aggregate on
    # a non-step series is *time-weighted* over the full bucket width, not a
    # simple mean of the sampled points - even though every point in this
    # bucket has the same value, the 4 points only cover minutes 5-50, so
    # the uncovered edges (0-5 and 50-60) pick up interpolation "bleed" from
    # the neighboring bucket's differing value (measured: ~51.21 and ~69.67
    # instead of the naive 50.0/70.0 mean). That's real CDF behavior our
    # code just passes through (see _parse_datapoints), not a bug in
    # Calculator/SeriesReducer - so this asserts a generous bound rather
    # than pretending the exact value is hand-derivable.
    query = CalculatorQuery(
        formula="{TEMP}",
        parameters=[
            TimeSeriesParameter(
                alias="TEMP",
                timeseries_instance_id=dataset.temp,
                aggregate_type="average",
                granularity="1h",
            )
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx(
        [50.0, 70.0], rel=0.05
    )


def test_two_aggregates_of_one_series_share_a_merged_request(
    calculator: Calculator, dataset: _Dataset
) -> None:
    """Probes the aggregate-merging branch of ``_build_requests``.

    Two parameters on the same (series, granularity) collapse into a *single*
    ``DatapointsQuery`` carrying ``aggregates=["sum", "max"]``, which
    ``_parse_datapoints`` then splits back apart with
    ``getattr(dp, aggregate_type)``. The mocked tests can only assert that
    split against a response we built ourselves; this asserts real CDF
    populates both columns, over one shared timestamp axis.

    ``produced`` has five distinct values inside hour 0, so ``sum`` (600) and
    ``max`` (140) differ - a swapped or duplicated column can't pass.
    """
    query = CalculatorQuery(
        formula="{TOTAL} - {PEAK}",
        parameters=[
            TimeSeriesParameter(
                alias="TOTAL",
                timeseries_instance_id=dataset.produced,
                aggregate_type="sum",
                granularity="1h",
            ),
            TimeSeriesParameter(
                alias="PEAK",
                timeseries_instance_id=dataset.produced,
                aggregate_type="max",
                granularity="1h",
            ),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx([460.0])


def test_one_series_read_both_raw_and_aggregated(
    calculator: Calculator, dataset: _Dataset
) -> None:
    """One instance id down both request paths at once.

    Raw and aggregated reads of the same series are deliberately *not*
    deduplicated into one request - they need different queries. Only the
    hour-0 bucket start coincides with a raw sample (both land exactly on
    ``_BASE``), so intersection leaves a single point: raw 100 + sum 600.
    """
    query = CalculatorQuery(
        formula="{RAW} + {TOTAL}",
        parameters=[
            TimeSeriesParameter(alias="RAW", timeseries_instance_id=dataset.produced),
            TimeSeriesParameter(
                alias="TOTAL",
                timeseries_instance_id=dataset.produced,
                aggregate_type="sum",
                granularity="1h",
            ),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert [dp.value for dp in result.datapoints] == pytest.approx([700.0])
    assert result.datapoints[0].timestamp == _BASE


def test_constant_parameter_broadcasts_against_a_real_series(
    calculator: Calculator, dataset: _Dataset
) -> None:
    query = CalculatorQuery(
        formula="{PRODUCED} * {LBS_TO_KG}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            ConstantParameter(alias="LBS_TO_KG", value=0.453592),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    expected = [v * 0.453592 for v in [100.0, 110.0, 120.0, 130.0, 140.0]]
    assert [dp.value for dp in result.datapoints] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Multiple time series per parameter (reducers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reducer", "expected"),
    [
        ("sum", [600.0, 630.0]),
        ("average", [200.0, 210.0]),
        ("min", [100.0, 110.0]),
        ("max", [300.0, 310.0]),
    ],
)
def test_multi_timeseries_reducer_against_real_hourly_aggregates(
    calculator: Calculator,
    dataset: _Dataset,
    reducer: ReducerType,
    expected: list[float],
) -> None:
    lines = MultiTimeSeriesParameter(
        alias="LINES",
        timeseries_instance_ids=[dataset.line_1, dataset.line_2, dataset.line_3],
        aggregate_type="sum",
        granularity="1h",
        reducer=reducer,
    )
    query = CalculatorQuery(formula="{LINES}", parameters=[lines])

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    # 3-hour window but only hours 0 and 1 have raw data; CDF must omit the
    # empty trailing bucket rather than returning a null/zero for it.
    assert len(result.datapoints) == 2
    assert [dp.value for dp in result.datapoints] == pytest.approx(expected)


def test_multi_timeseries_reducer_drops_buckets_missing_from_any_series(
    calculator: Calculator, dataset: _Dataset
) -> None:
    """The key probe for SeriesReducer's documented combining behavior.

    gap_b has no raw datapoints in the first hourly bucket. If CDF's
    aggregate API genuinely omits empty buckets (rather than returning a
    null/zero datapoint for them), SeriesReducer's timestamp-intersection
    logic must drop the first hour entirely rather than treating the
    missing value as zero. If this assertion fails, either that CDF
    assumption is wrong or SeriesReducer has a bug - both are real gaps
    worth investigating (see series_reducer.py and CALCULATOR.md's
    "Combining behavior" section).
    """
    gap_param = MultiTimeSeriesParameter(
        alias="GAP",
        timeseries_instance_ids=[dataset.gap_a, dataset.gap_b],
        aggregate_type="sum",
        granularity="1h",
        reducer="sum",
    )
    query = CalculatorQuery(formula="{GAP}", parameters=[gap_param])

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert len(result.datapoints) == 1, (
        "Expected only the second hourly bucket to survive (gap_b has no "
        f"data in the first hour); got {len(result.datapoints)} datapoint(s): "
        f"{[(dp.timestamp, dp.value) for dp in result.datapoints]}"
    )
    assert result.datapoints[0].value == pytest.approx(56.0)  # gap_a 6.0 + gap_b 50.0


def test_formula_intersects_reduced_series_with_a_gapped_sibling(
    calculator: Calculator, dataset: _Dataset
) -> None:
    """Reducer intersection and formula-level intersection against real CDF.

    LINES has hourly sums in both hour 0 and hour 1; GAP (see the test
    above) only survives in hour 1. Default ``intersect`` alignment
    must keep only that shared hour - not fail, and not invent a zero for
    GAP's missing first bucket.
    """
    lines = MultiTimeSeriesParameter(
        alias="LINES",
        timeseries_instance_ids=[dataset.line_1, dataset.line_2, dataset.line_3],
        aggregate_type="sum",
        granularity="1h",
        reducer="sum",
    )
    gap = MultiTimeSeriesParameter(
        alias="GAP",
        timeseries_instance_ids=[dataset.gap_a, dataset.gap_b],
        aggregate_type="sum",
        granularity="1h",
        reducer="sum",
    )
    query = CalculatorQuery(formula="{LINES} + {GAP}", parameters=[lines, gap])

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    assert len(result.datapoints) == 1, (
        "Expected only the hour where LINES and GAP overlap; "
        f"got {len(result.datapoints)} datapoint(s): "
        f"{[(dp.timestamp, dp.value) for dp in result.datapoints]}"
    )
    assert result.datapoints[0].value == pytest.approx(686.0)  # 630 + 56


# ---------------------------------------------------------------------------
# Combined / batched scenarios
# ---------------------------------------------------------------------------


def test_complex_formula_combining_reducer_and_constants(
    calculator: Calculator, dataset: _Dataset
) -> None:
    lines_kg = MultiTimeSeriesParameter(
        alias="LINES_KG",
        timeseries_instance_ids=[dataset.line_1, dataset.line_2, dataset.line_3],
        aggregate_type="sum",
        granularity="1h",
        reducer="sum",
    )
    kg_to_lbs = ConstantParameter(alias="KG_TO_LBS", value=2.20462)
    target = ConstantParameter(alias="TARGET", value=1000.0)
    query = CalculatorQuery(
        formula="(({LINES_KG} * {KG_TO_LBS}) / {TARGET}) * 100",
        parameters=[lines_kg, kg_to_lbs, target],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    expected = [(v * 2.20462 / 1000.0) * 100 for v in [600.0, 630.0]]
    assert [dp.value for dp in result.datapoints] == pytest.approx(expected)


def test_chunked_requests_keep_each_series_on_its_own_alias(
    calculator: Calculator, dataset: _Dataset, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CDF must answer in request order, including across separate calls.

    ``_build_requests`` hands back positional indexes into a flat response
    list, so a reordered (or differently chunked) CDF response would silently
    attach every value to the wrong parameter. Shrinking the chunk size
    splits four out-of-order series across two concurrent requests, exercising
    both within-chunk and across-chunk ordering without having to provision
    the 100+ instances the real limit would need.

    Each alias is scaled by a different power of ten, so any permutation
    produces a different number.
    """
    monkeypatch.setattr(datapoints_retrieval, "_MAX_TIME_SERIES_PER_REQUEST", 2)

    query = CalculatorQuery(
        formula="{L3} * 1000 + {L1} * 100 + {GA} * 10 + {L2}",
        parameters=[
            TimeSeriesParameter(alias="L3", timeseries_instance_id=dataset.line_3),
            TimeSeriesParameter(alias="L1", timeseries_instance_id=dataset.line_1),
            TimeSeriesParameter(alias="GA", timeseries_instance_id=dataset.gap_a),
            TimeSeriesParameter(alias="L2", timeseries_instance_id=dataset.line_2),
        ],
    )

    result = _calculate(calculator, query, _WINDOW_START, _WINDOW_END)

    # minute 15: 300*1000 + 100*100 + 5*10 + 200
    # minute 75: 310*1000 + 110*100 + 6*10 + 210
    assert [dp.value for dp in result.datapoints] == pytest.approx([310250.0, 321270.0])


def test_calculate_multiples_batches_real_queries_together(
    calculator: Calculator, dataset: _Dataset
) -> None:
    simple_query = CalculatorQuery(
        formula="{PRODUCED} - {SCRAP}",
        parameters=[
            TimeSeriesParameter(
                alias="PRODUCED", timeseries_instance_id=dataset.produced
            ),
            TimeSeriesParameter(alias="SCRAP", timeseries_instance_id=dataset.scrap),
        ],
    )
    aggregate_query = CalculatorQuery(
        formula="{TEMP}",
        parameters=[
            TimeSeriesParameter(
                alias="TEMP",
                timeseries_instance_id=dataset.temp,
                aggregate_type="average",
                granularity="1h",
            )
        ],
    )
    reducer_query = CalculatorQuery(
        formula="{LINES}",
        parameters=[
            MultiTimeSeriesParameter(
                alias="LINES",
                timeseries_instance_ids=[
                    dataset.line_1,
                    dataset.line_2,
                    dataset.line_3,
                ],
                aggregate_type="sum",
                granularity="1h",
                reducer="sum",
            )
        ],
    )

    simple_result, aggregate_result, reducer_result = _calculate_multiples(
        calculator,
        [simple_query, aggregate_query, reducer_query],
        _WINDOW_START,
        _WINDOW_END,
    )

    assert [dp.value for dp in simple_result.datapoints] == pytest.approx(
        [90.0, 110.0, 115.0, 110.0, 138.0]
    )
    # Wide tolerance: see the time-weighted-average comment on
    # test_single_aggregate_hourly_average.
    assert [dp.value for dp in aggregate_result.datapoints] == pytest.approx(
        [50.0, 70.0], rel=0.05
    )
    assert [dp.value for dp in reducer_result.datapoints] == pytest.approx(
        [600.0, 630.0]
    )
