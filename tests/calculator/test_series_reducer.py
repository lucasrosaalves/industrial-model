from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from industrial_model.calculator.series_reducer import SeriesReducer

_T0 = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
_T1 = datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
_T2 = datetime(2024, 1, 1, 2, 0, tzinfo=UTC)


def _series(*pairs: tuple[datetime, float]) -> list[tuple[datetime, float]]:
    return list(pairs)


def _reduce_sum_via_align_filled(
    reducer: SeriesReducer,
    lines: list[list[tuple[datetime, float]]],
    fill_value: float,
) -> list[tuple[datetime, float]]:
    filled = reducer.align_filled(lines, [fill_value] * len(lines))
    return [
        (ts, sum(leaf[i][1] for leaf in filled))
        for i, (ts, _) in enumerate(filled[0])
    ]


# ---------------------------------------------------------------------------
# Zero / one series (no reduction needed)
# ---------------------------------------------------------------------------


def test_empty_series_list_returns_empty_list() -> None:
    reducer = SeriesReducer()

    assert reducer.reduce([], "sum") == []


def test_single_series_is_returned_as_a_copy() -> None:
    reducer = SeriesReducer()
    series = _series((_T0, 1.0), (_T1, 2.0))

    result = reducer.reduce([series], "sum")

    assert result == series
    assert result is not series


def test_single_series_is_returned_unchanged_even_with_reducer_set() -> None:
    # A reducer is meaningless with only one series, so it must be ignored
    # rather than applied or rejected.
    reducer = SeriesReducer()
    series = _series((_T0, 1.0), (_T1, 2.0))

    assert reducer.reduce([series], "max") == series


def test_single_empty_series_is_returned_unchanged() -> None:
    reducer = SeriesReducer()

    assert reducer.reduce([[]], "sum") == []


def test_single_series_is_normalized_like_a_multi_series_reduction() -> None:
    # Normalization must not depend on how many series were passed, otherwise
    # ``{A}`` and ``{A} + {B}`` would disagree about what "A" is.
    reducer = SeriesReducer()
    series = _series((_T1, 2.0), (_T0, 1.0), (_T0, 9.0))

    assert reducer.reduce([series], "sum") == [(_T0, 9.0), (_T1, 2.0)]


# ---------------------------------------------------------------------------
# Reducer correctness
# ---------------------------------------------------------------------------


def test_sum_reducer_adds_values_across_series() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T1, 2.0))
    series_b = _series((_T0, 10.0), (_T1, 20.0))

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == [(_T0, 11.0), (_T1, 22.0)]


def test_min_reducer_takes_lowest_value_per_timestamp() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 5.0))
    series_b = _series((_T0, -3.0))
    series_c = _series((_T0, 10.0))

    result = reducer.reduce([series_a, series_b, series_c], "min")

    assert result == [(_T0, -3.0)]


def test_max_reducer_takes_highest_value_per_timestamp() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 5.0))
    series_b = _series((_T0, -3.0))
    series_c = _series((_T0, 10.0))

    result = reducer.reduce([series_a, series_b, series_c], "max")

    assert result == [(_T0, 10.0)]


def test_average_reducer_takes_mean_value_per_timestamp() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 4.0))
    series_b = _series((_T0, 10.0))

    result = reducer.reduce([series_a, series_b], "average")

    assert result == [(_T0, 7.0)]


def test_average_reducer_over_three_series() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 3.0))
    series_b = _series((_T0, 6.0))
    series_c = _series((_T0, 9.0))

    result = reducer.reduce([series_a, series_b, series_c], "average")

    assert result == [(_T0, 6.0)]


def test_reducer_handles_negative_and_fractional_values() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, -1.5))
    series_b = _series((_T0, 2.5))

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == [(_T0, 1.0)]


# ---------------------------------------------------------------------------
# Timestamp alignment edge cases
# ---------------------------------------------------------------------------


def test_only_common_timestamps_survive_reduction() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T1, 2.0), (_T2, 3.0))
    series_b = _series((_T0, 10.0), (_T2, 30.0))  # missing _T1

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == [(_T0, 11.0), (_T2, 33.0)]


def test_disjoint_timestamps_produce_empty_result() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0))
    series_b = _series((_T1, 2.0))

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == []


def test_one_empty_series_among_many_produces_empty_result() -> None:
    # An empty series has no timestamps, so its intersection with anything
    # else is empty too.
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T1, 2.0))
    series_b: list[tuple[datetime, float]] = []

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == []


def test_all_empty_series_produce_empty_result() -> None:
    reducer = SeriesReducer()

    result = reducer.reduce([[], []], "sum")

    assert result == []


def test_result_is_sorted_by_timestamp_regardless_of_input_order() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T2, 3.0), (_T0, 1.0), (_T1, 2.0))
    series_b = _series((_T1, 20.0), (_T2, 30.0), (_T0, 10.0))

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == [(_T0, 11.0), (_T1, 22.0), (_T2, 33.0)]


def test_reduction_is_symmetric_regardless_of_series_argument_order() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 5.0), (_T1, 7.0))
    series_b = _series((_T0, 1.0), (_T1, 2.0))

    forward = reducer.reduce([series_a, series_b], "min")
    backward = reducer.reduce([series_b, series_a], "min")

    assert forward == backward == [(_T0, 1.0), (_T1, 2.0)]


def test_duplicate_timestamp_within_a_series_keeps_the_last_value() -> None:
    # Each series is collapsed into a timestamp -> value map before
    # reduction, so a repeated timestamp resolves to its last occurrence.
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T0, 99.0))
    series_b = _series((_T0, 10.0))

    result = reducer.reduce([series_a, series_b], "sum")

    assert result == [(_T0, 109.0)]


def test_four_series_reduced_together() -> None:
    reducer = SeriesReducer()
    series = [_series((_T0, float(i))) for i in range(1, 5)]  # 1.0, 2.0, 3.0, 4.0

    result = reducer.reduce(series, "sum")

    assert result == [(_T0, 10.0)]


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_reduce_does_not_mutate_input_series() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T2, 3.0), (_T0, 1.0))
    series_b = _series((_T0, 10.0), (_T2, 30.0))
    original_a = list(series_a)
    original_b = list(series_b)

    reducer.reduce([series_a, series_b], "sum")

    assert series_a == original_a
    assert series_b == original_b


def test_large_gapped_series_intersect_and_sum() -> None:
    reducer = SeriesReducer()
    n = 20_000
    base = _T0
    series_a = [(base + timedelta(seconds=i), float(i)) for i in range(n) if i % 3 != 0]
    series_b = [
        (base + timedelta(seconds=i), float(i * 10)) for i in range(n) if i % 5 != 0
    ]
    series_c = [
        (base + timedelta(seconds=i), float(i * 100)) for i in range(n) if i % 7 != 0
    ]

    result = reducer.reduce([series_a, series_b, series_c], "sum")

    expected_indexes = [i for i in range(n) if i % 3 and i % 5 and i % 7]
    assert [ts for ts, _ in result] == [
        base + timedelta(seconds=i) for i in expected_indexes
    ]
    assert [val for _, val in result] == [
        float(i + i * 10 + i * 100) for i in expected_indexes
    ]


def test_align_filters_each_series_to_common_timestamps() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T1, 2.0), (_T2, 3.0))
    series_b = _series((_T0, 10.0), (_T2, 30.0))

    aligned = reducer.align([series_a, series_b])

    assert aligned == [
        [(_T0, 1.0), (_T2, 3.0)],
        [(_T0, 10.0), (_T2, 30.0)],
    ]


def test_align_empty_leaf_makes_every_series_empty() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T0, 1.0), (_T1, 2.0))

    assert reducer.align([series_a, []]) == [[], []]


def test_align_single_series_returns_a_copy() -> None:
    reducer = SeriesReducer()
    series = _series((_T0, 1.0), (_T1, 2.0))

    aligned = reducer.align([series])

    assert aligned == [series]
    assert aligned[0] is not series


def test_align_normalizes_a_single_series() -> None:
    reducer = SeriesReducer()
    series = _series((_T1, 2.0), (_T0, 1.0), (_T0, 9.0))

    assert reducer.align([series]) == [[(_T0, 9.0), (_T1, 2.0)]]


def test_align_does_not_mutate_input_series() -> None:
    reducer = SeriesReducer()
    series_a = _series((_T2, 3.0), (_T0, 1.0))
    series_b = _series((_T0, 10.0), (_T2, 30.0))
    original_a = list(series_a)
    original_b = list(series_b)

    reducer.align([series_a, series_b])

    assert series_a == original_a
    assert series_b == original_b


# ---------------------------------------------------------------------------
# reduce with a fill value
# ---------------------------------------------------------------------------


def test_reduce_with_fill_value_combines_on_the_union_of_timestamps() -> None:
    reducer = SeriesReducer()
    line_a = _series((_T0, 5.0), (_T1, 5.0), (_T2, 5.0))
    line_b = _series((_T0, 3.0), (_T2, 3.0))

    result = reducer.reduce([line_a, line_b], "sum", 0.0)

    # T1 keeps line A's count instead of being dropped.
    assert result == [(_T0, 8.0), (_T1, 5.0), (_T2, 8.0)]


def test_reduce_with_fill_value_keeps_a_series_when_another_is_empty() -> None:
    reducer = SeriesReducer()
    line_a = _series((_T0, 5.0), (_T1, 5.0))

    assert reducer.reduce([line_a, []], "sum", 0.0) == line_a


def test_reduce_sum_non_zero_fill_counts_empty_series() -> None:
    reducer = SeriesReducer()
    line_a = _series((_T0, 10.0), (_T1, 20.0))

    assert reducer.reduce([line_a, []], "sum", 5.0) == [(_T0, 15.0), (_T1, 25.0)]
    assert reducer.reduce([line_a, []], "sum", 5.0) == _reduce_sum_via_align_filled(
        reducer, [line_a, []], 5.0
    )


def test_reduce_with_fill_value_fills_before_reducing() -> None:
    reducer = SeriesReducer()
    a = _series((_T0, 4.0), (_T1, 6.0))
    b = _series((_T1, 2.0))

    assert reducer.reduce([a, b], "average", 0.0) == [(_T0, 2.0), (_T1, 4.0)]
    assert reducer.reduce([a, b], "min", -1.0) == [(_T0, -1.0), (_T1, 2.0)]


def test_reduce_with_fill_value_of_empty_series_is_empty() -> None:
    assert SeriesReducer().reduce([[], []], "sum", 0.0) == []


@pytest.mark.parametrize("fill_value", [0.0, -1.0, 5.0])
def test_reduce_sum_filled_matches_union_grid(fill_value: float) -> None:
    """Filled sum must match align_filled + sum for scrap-style misalignment."""
    reducer = SeriesReducer()
    base = datetime(2024, 6, 1, tzinfo=UTC)
    lines = [
        [
            (base + timedelta(minutes=i), float(i % 7))
            for i in range(0, 120, 3 + (n % 4))
        ]
        for n in range(40)
    ]
    assert reducer.reduce(lines, "sum", fill_value) == _reduce_sum_via_align_filled(
        reducer, lines, fill_value
    )


@pytest.mark.parametrize("fill_value", [0.0, 3.0])
def test_reduce_sum_filled_with_some_empty_inputs(fill_value: float) -> None:
    reducer = SeriesReducer()
    base = datetime(2024, 6, 1, tzinfo=UTC)
    lines: list[list[tuple[datetime, float]]] = [
        [(base, 1.0), (base + timedelta(hours=1), 2.0)],
        [],
        [(base + timedelta(hours=1), 4.0)],
        [],
    ]
    assert reducer.reduce(lines, "sum", fill_value) == _reduce_sum_via_align_filled(
        reducer, lines, fill_value
    )


# ---------------------------------------------------------------------------
# align_filled
# ---------------------------------------------------------------------------


def test_align_filled_fills_a_series_missing_a_required_timestamp() -> None:
    reducer = SeriesReducer()
    required = _series((_T0, 10.0), (_T1, 20.0), (_T2, 30.0))
    counts = _series((_T1, 5.0))

    aligned = reducer.align_filled([required, counts], [None, 0.0])

    assert aligned == [
        [(_T0, 10.0), (_T1, 20.0), (_T2, 30.0)],
        [(_T0, 0.0), (_T1, 5.0), (_T2, 0.0)],
    ]


def test_align_filled_never_adds_a_timestamp_a_required_series_lacks() -> None:
    reducer = SeriesReducer()
    required = _series((_T1, 20.0))
    counts = _series((_T0, 1.0), (_T1, 2.0), (_T2, 3.0))

    aligned = reducer.align_filled([required, counts], [None, 0.0])

    assert aligned == [[(_T1, 20.0)], [(_T1, 2.0)]]


def test_align_filled_intersects_required_series() -> None:
    reducer = SeriesReducer()
    a = _series((_T0, 1.0), (_T1, 2.0))
    b = _series((_T1, 3.0), (_T2, 4.0))
    c = _series()

    aligned = reducer.align_filled([a, b, c], [None, None, 9.0])

    assert aligned == [[(_T1, 2.0)], [(_T1, 3.0)], [(_T1, 9.0)]]


def test_align_filled_uses_the_union_when_every_series_fills() -> None:
    reducer = SeriesReducer()
    a = _series((_T2, 1.0), (_T0, 2.0))
    b = _series((_T1, 3.0))

    aligned = reducer.align_filled([a, b], [0.0, -1.0])

    assert aligned == [
        [(_T0, 2.0), (_T1, 0.0), (_T2, 1.0)],
        [(_T0, -1.0), (_T1, 3.0), (_T2, -1.0)],
    ]


def test_align_filled_empty_required_series_is_empty() -> None:
    reducer = SeriesReducer()

    aligned = reducer.align_filled([_series(), _series((_T0, 1.0))], [None, 0.0])

    assert aligned == [[], []]


def test_align_filled_keeps_the_last_value_of_a_duplicate_timestamp() -> None:
    reducer = SeriesReducer()

    aligned = reducer.align_filled(
        [_series((_T0, 1.0), (_T0, 2.0)), _series()], [None, 0.0]
    )

    assert aligned == [[(_T0, 2.0)], [(_T0, 0.0)]]


def test_align_filled_rejects_mismatched_fill_values() -> None:
    reducer = SeriesReducer()

    with pytest.raises(ValueError, match="fill value"):
        reducer.align_filled([_series((_T0, 1.0))], [])


def test_align_filled_returns_series_that_already_share_timestamps() -> None:
    reducer = SeriesReducer()
    a = _series((_T0, 1.0), (_T1, 2.0))
    b = _series((_T0, 3.0), (_T1, 4.0))

    assert reducer.align_filled([a, b], [None, 0.0]) == [a, b]
