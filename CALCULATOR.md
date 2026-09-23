# Calculator

The `industrial_model.calculator` package computes derived time series from raw Cognite Data Fusion (CDF) datapoints. You describe a formula using `{PLACEHOLDER}` parameters, point each placeholder at a constant, a single CDF time series (raw or aggregated), or several time series combined with a reducer — and the calculator fetches the datapoints, aligns them, and evaluates the formula element-by-element.

It's built from three layers:

- **`Calculator`** — the CDF-facing layer. Resolves `CalculatorQuery` objects into datapoint requests, deduplicates them, retrieves them in a single SDK call via the async CDF client, and evaluates the formula over the results. `calculate` and `calculate_multiples` are async.
- **`DatapointsRetriever` / `SeriesReducer`** — build deduplicated CDF requests per unique (time series, aggregate, granularity), and combine multiple time series into one when a parameter references more than one.
- **`formula_expression.evaluate`** — a standalone, CDF-free formula engine. It compiles a small, safe arithmetic expression language (a restricted subset of Python) to an AST and evaluates it over plain numeric sequences. It has no dependency on `Calculator` and can be used on its own for testing or non-CDF data.

---

## Installation

No extra install is required — `cognite-sdk` and `pydantic` are core dependencies of `industrial-model`.

```bash
pip install industrial-model
```

---

## Quick start: `Calculator`

```python
from datetime import datetime, timedelta, UTC

from cognite.client import CogniteClient
from industrial_model.calculator import Calculator, CalculatorQuery, TimeSeriesParameter
from industrial_model.models import InstanceId

client = CogniteClient()
calculator = Calculator(client)  # uses client.get_async_client() for CDF retrieve

query = CalculatorQuery(
    formula="{PRODUCED} - {SCRAP}",
    parameters=[
        TimeSeriesParameter(
            alias="PRODUCED",
            timeseries_instance_id=InstanceId(space="my-space", external_id="ts_produced"),
        ),
        TimeSeriesParameter(
            alias="SCRAP",
            timeseries_instance_id=InstanceId(space="my-space", external_id="ts_scrap"),
        ),
    ],
)

end = datetime.now(tz=UTC)
start = end - timedelta(days=1)

result = await calculator.calculate(query, start, end)
# result.query:      CalculatorQuery  (the query that produced this result)
# result.datapoints: list[DataPoint], each with .timestamp: datetime and .value: float
# result.inputs:     dict[str, list[DataPoint]] — aligned series used by the formula, keyed by alias
#                    result.inputs[alias][i] is the point used to compute result.datapoints[i]

for dp in result.datapoints:
    print(dp.timestamp, dp.value)
```

`result.query` is the exact `CalculatorQuery` that was passed in — handy when matching results back to their originating query after `calculate_multiples`. `result.inputs` is the aligned series that the formula actually evaluated: after retrieval, any `MultiTimeSeriesParameter` reduction, timestamp alignment, and constant broadcast. Each input series is a `list[DataPoint]` sharing the same timestamps as `datapoints`; `inputs[alias][i]` is the point used to compute `datapoints[i]`. These series are already in memory at evaluation time, so returning them does not refetch from CDF.

Each `DataPoint.timestamp` comes from the **shared time axis** of the query's time-series parameters (`TimeSeriesParameter` or `MultiTimeSeriesParameter`). By default (`alignment="intersect"`) that axis is the **intersection** of their timestamps: a point is emitted only when every time-series parameter has a value at that exact timestamp. Set `alignment="strict"` to require identical timestamps and raise `ParameterTimestampError` if they differ. `ConstantParameter` values don't participate in this alignment — they are broadcast to the resulting length. See [Constants](#constants) and [Timestamp alignment](#timestamp-alignment) below.

### Batching multiple queries

Use `calculate_multiples` when you need several formulas evaluated over the same window. All time-series parameters across all queries are fetched in one retrieval pass. Identical time series requests (same instance id, aggregate, and granularity) are deduplicated even across queries. All of them go to CDF in **one** SDK `retrieve` call; the SDK packs them into requests of up to 100 series and pages each to the end, using `global_config.concurrency_settings.datapoints.read` requests in flight (raise it before the first request for large batches). Pass keyword-only ``timezone=`` so every hour-and-longer aggregate in the batch uses the same calendar (see [Calendar timezones](#calendar-timezones)):

```python
results = await calculator.calculate_multiples(
    [
        CalculatorQuery(formula="{A} + {B}", parameters=[param_a, param_b]),
        CalculatorQuery(formula="{A} * 2", parameters=[param_a]),  # {A} reused, not refetched
    ],
    start,
    end,
)
# results[0], results[1] -> CalculationResult, one per input query, same order
```

### Debug logs

The calculator uses the standard library `logging` module and is silent by default. Set the `industrial_model.calculator` logger to `DEBUG` to see where a run spends time:

```python
import logging

logging.basicConfig()
logging.getLogger("industrial_model.calculator").setLevel(logging.DEBUG)
```

Each `calculate` / `calculate_multiples` call then logs a single-line stage breakdown (`build_requests`, `retrieve`, `parse`, `reduce`, `align`, `evaluate`, `assemble`) and names the bottleneck — the exclusive stage that took the longest. The summary is emitted even if the call fails (`status=error`). CDF retrieve is shared across all queries in a `calculate_multiples` batch, so it appears once in the summary. DEBUG also logs the retrieve (series count and duration) and each query's formula, input lengths, and aligned point count.

### One calculation at a time per client

Run `calculate` / `calculate_multiples` one after another on a given `CogniteClient`. Cognite SDK 8.x shares one datapoints request semaphore per client, and a `retrieve` that finds it exhausted returns only the first page of every series, with no error. A single call already uses the SDK's full read concurrency. The retriever asks again when a page is long enough to be that first page and stops when a page brings nothing new; that does not make overlapping calls on the same client safe.

---

## Data models

```python
from industrial_model.calculator import (
    AlignmentMode,
    CalculatorError,
    CalculatorParameter,
    CalculatorQuery,
    CalculationResult,
    ConstantParameter,
    DataPoint,
    MultiTimeSeriesParameter,
    ReducerType,
    TimeSeriesParameter,
)
```

`CalculatorParameter` is a discriminated union of three parameter kinds, keyed on a `type` field that's set automatically when you instantiate any of them directly. You only need `type` explicitly when building a parameter from a raw dict/JSON payload (e.g. `CalculatorQuery.model_validate(payload)`) — see [Building parameters from raw data](#building-parameters-from-raw-data).

| Model | `type` tag | Fields | Notes |
|---|---|---|---|
| `ConstantParameter` | `"constant"` | `alias: str`, `value: float` | A fixed scalar, broadcast across every timestamp in the result. No CDF call is made for it. |
| `TimeSeriesParameter` | `"single_timeseries"` | `alias: str`, `timeseries_instance_id: InstanceId`, `aggregate_type: Aggregate \| None`, `granularity: str \| None` | Exactly one CDF time series. |
| `MultiTimeSeriesParameter` | `"multi_timeseries"` | `alias: str`, `timeseries_instance_ids: list[InstanceId]` (≥ 2, unique), `aggregate_type: Aggregate \| None`, `granularity: str \| None`, `reducer: ReducerType` | Two or more CDF time series, combined with `reducer` — see [Multiple time series per parameter](#multiple-time-series-per-parameter). `reducer` has no default; you must always supply one. Duplicate instance ids are rejected. |
| `ReducerType` | — | `Literal["min", "max", "sum", "average"]` | How multiple time series for one parameter are combined into one. |
| `AlignmentMode` | — | `Literal["intersect", "strict"]` | How time-series parameters in a query are joined on time. Default is `"intersect"`. |
| `CalculatorQuery` | — | `formula: str`, `parameters: list[CalculatorParameter]`, `alignment: AlignmentMode` (default `"intersect"`) | One query = one formula + the parameters it references. Every parameter's `alias` must be unique within the query — see below. `alignment` controls how time-series parameters are joined on time — see [Timestamp alignment](#timestamp-alignment). |
| `DataPoint` | — | `timestamp: datetime`, `value: float` | A `NamedTuple` timestamped numeric value. Used both for the formula result (`datapoints`) and for each aligned input series. Unpack as `ts, value = dp`. Not a Pydantic model — see below. |
| `CalculationResult` | — | `query: CalculatorQuery`, `datapoints: list[DataPoint]`, `inputs: dict[str, list[DataPoint]]` | Frozen dataclass output of `Calculator.calculate`. `query` is the originating query; `datapoints` has one `DataPoint` per aligned index; `inputs` is the aligned parameter series the formula evaluated (`inputs[alias][i]` was used to compute `datapoints[i]`). Not a Pydantic model — see below. |

Query and parameter types (`CalculatorQuery`, `ConstantParameter`, `TimeSeriesParameter`, `MultiTimeSeriesParameter`) are Pydantic so construction and `model_validate` still check aliases, discriminators, and aggregate/granularity rules. `DataPoint` and `CalculationResult` are not: assembling a result builds one `DataPoint` per timestamp for the output and for every input series, and Pydantic validation on that path dominated calculate time. They stay a `NamedTuple` and a frozen dataclass so assemble is just object construction. Attribute access is unchanged (`dp.timestamp`, `dp.value`); `model_dump` / `model_validate` are not available on these two types.

In all three parameter kinds, `alias` is the name used inside `{...}` placeholders in the formula. `CalculatorQuery` rejects two parameters sharing the same `alias` at construction time:

```python
# ✗ raises ValidationError — "duplicate parameter alias(es): A"
CalculatorQuery(
    formula="{A}",
    parameters=[
        ConstantParameter(alias="A", value=1.0),
        ConstantParameter(alias="A", value=2.0),
    ],
)
```

### Raw vs. aggregated time series

- Leave `aggregate_type=None` to fetch raw datapoints for the time series.
- Set `aggregate_type` (e.g. `"average"`, `"sum"`, `"max"`, `"min"`, `"count"`, ...) to fetch a CDF aggregate. `granularity` (e.g. `"1h"`, `"1d"`) is **required** whenever `aggregate_type` is set — construction raises a `ValidationError` otherwise.

```python
TimeSeriesParameter(
    alias="AVG_TEMP",
    timeseries_instance_id=InstanceId(space="my-space", external_id="ts_temp"),
    aggregate_type="average",
    granularity="1h",
)
```

### Calendar timezones

CDF stores datapoints as UTC instants. Calendar aggregates (`hour`, `day`, `month`) default to **UTC midnight / hour / month**. Pass keyword-only ``timezone=`` on `calculate` / `calculate_multiples` so every such aggregate in that call uses the same local calendar, including DST. CDF accepts IANA ids (`America/New_York`, `Europe/Oslo`) and fixed offsets (`UTC+05:30`, `UTC+01:00`); omit the argument for UTC.

`timezone` does **not** change raw datapoints or sub-hour granularities (`1m`, `15m`, …). It also does **not** reinterpret `start` / `end`: those stay the UTC instants you pass. For “the New York calendar day 2024-01-15” pass the UTC instants of that day’s NY midnight, *and* `timezone="America/New_York"`. Result timestamps remain UTC instants of the local bucket start (what CDF returns). When `rolling_average` fills an hour-or-longer grid, those steps use the same calendar — see [Rolling average](#rolling-average).

The argument is **per call**, not per query or parameter. Group entities that share a timezone into one `calculate_multiples`; run another call for a different timezone. The string is forwarded to CDF unchanged; a blank or unknown id fails on retrieve the same way a direct datapoints call would.

```python
result = await calculator.calculate(
    CalculatorQuery(
        formula="{GQ} + {SQ}",
        parameters=[
            TimeSeriesParameter(
                alias="GQ",
                timeseries_instance_id=good,
                aggregate_type="sum",
                granularity="1d",
            ),
            TimeSeriesParameter(
                alias="SQ",
                timeseries_instance_id=scrap,
                aggregate_type="sum",
                granularity="1d",
            ),
        ],
    ),
    start,
    end,
    timezone="America/New_York",
)
```

### Constants

Use `ConstantParameter` for fixed values — conversion factors, thresholds, headcount for a shift, etc. — that don't come from a time series:

```python
from industrial_model.calculator import ConstantParameter, TimeSeriesParameter, CalculatorQuery

query = CalculatorQuery(
    formula="{PRODUCED} * {LBS_TO_KG}",
    parameters=[
        TimeSeriesParameter(
            alias="PRODUCED",
            timeseries_instance_id=InstanceId(space="my-space", external_id="ts_produced"),
        ),
        ConstantParameter(alias="LBS_TO_KG", value=0.453592),
    ],
)
```

`Calculator` never contacts CDF for a `ConstantParameter` — its `value` is broadcast onto the timestamps established by the query's time-series parameters. A query made **only** of `ConstantParameter`s has no time axis to broadcast onto, and raises `MissingTimeAxisError`: the calculator computes time series, and there is nothing to timestamp a pure-constant formula against.

### Multiple time series per parameter

Use `MultiTimeSeriesParameter` when a formula input is really an aggregation over several time series — it takes `timeseries_instance_ids` (two or more) and a required `reducer`. The calculator fetches every listed time series (deduplicated and batched just like single-series parameters) and combines them **element-wise, by timestamp**, before the formula ever sees them:

```python
from industrial_model.calculator import MultiTimeSeriesParameter

total_output = MultiTimeSeriesParameter(
    alias="LINE_TOTAL",
    timeseries_instance_ids=[
        InstanceId(space="plant", external_id="ts_line_1"),
        InstanceId(space="plant", external_id="ts_line_2"),
        InstanceId(space="plant", external_id="ts_line_3"),
    ],
    aggregate_type="sum",
    granularity="1h",
    reducer="sum",  # hourly total across all three lines
)
```

If you only have one time series for a parameter, use `TimeSeriesParameter` instead — `MultiTimeSeriesParameter` requires at least two instance ids and rejects zero or one at construction time.

**Combining behavior — read this before relying on it:**

- Series are combined by **intersecting on timestamp**: a timestamp survives into the reduced series only if *every* referenced time series has a value at that exact timestamp. This is stricter than a positional zip — it won't silently pair up unrelated points if one series has a gap the others don't.
- Because of that, **use `aggregate_type` + `granularity`** whenever you reduce multiple time series. Aggregated queries bucket every series onto the same aligned time grid, so timestamps line up; raw datapoints from independent series almost never share exact timestamps, and reducing raw series will typically collapse to an empty result.
- If the referenced series have no timestamps in common at all, the parameter's series — and therefore the formula's result — is empty.
- Validation happens at construction time: `MultiTimeSeriesParameter` raises a `pydantic.ValidationError` if it has fewer than two `timeseries_instance_ids`, if any instance id is repeated, or if `reducer` is omitted entirely (it has no default).

```python
# ✗ raises ValidationError — "must reference at least two timeseries"
MultiTimeSeriesParameter(
    alias="LINE_TOTAL",
    timeseries_instance_ids=[InstanceId(space="plant", external_id="ts_line_1")],
    reducer="sum",
)
```

### Building parameters from raw data

If you're constructing `CalculatorQuery` from a dict or JSON payload (e.g. `CalculatorQuery.model_validate(payload)`) rather than instantiating the parameter classes directly in Python, each parameter dict **must** include the `type` tag — it's what tells the discriminated union which class to use, and unlike constructing the class directly, there's no default to fall back on:

```python
# ✗ raises ValidationError — "Unable to extract tag using discriminator 'type'"
CalculatorQuery.model_validate({
    "formula": "{A}",
    "parameters": [
        {"alias": "A", "timeseries_instance_id": {"space": "s", "external_id": "x"}},
    ],
})

# ✓
CalculatorQuery.model_validate({
    "formula": "{A}",
    "parameters": [
        {
            "type": "single_timeseries",
            "alias": "A",
            "timeseries_instance_id": {"space": "s", "external_id": "x"},
        },
    ],
})
```

`query.model_dump()` always includes `type`, so round-tripping a query you already built in Python through `model_dump()` → `model_validate()` works without extra care.

### Timestamp alignment

Element-wise formulas like `{A} + {B}` are evaluated on a single time axis. `CalculatorQuery.alignment` chooses how that axis is built from the query's time-series parameters (after any `MultiTimeSeriesParameter` reduction):

| Mode | Behavior |
|---|---|
| `"intersect"` (default) | Keep timestamps present in **every** time-series parameter. Gaps in one series drop that timestamp from the result rather than failing the query. If there is no overlap, the result is empty. |
| `"strict"` | Require identical timestamps at every index. Raise `ParameterTimestampError` if they differ. Use this when a missing bucket should fail the job rather than be omitted. Grid fill for `rolling_average` does not bypass this check. |

This is the same intersection rule `SeriesReducer` uses inside a `MultiTimeSeriesParameter`. Constants are broadcast onto whatever timestamps remain.

```python
# default: evaluate only where A and B both have a point
CalculatorQuery(formula="{A} + {B}", parameters=[param_a, param_b])

# fail if A and B don't share the exact same timestamps
CalculatorQuery(
    formula="{A} + {B}",
    parameters=[param_a, param_b],
    alignment="strict",
)
```

---

## The formula engine: `evaluate`

`evaluate` is a pure function with no CDF dependency — useful for unit testing formulas or running the calculator engine over data from any source:

```python
from industrial_model.calculator import evaluate

evaluate("{A} + {B}", {"A": [1.0, 2.0], "B": [10.0, 20.0]})
# -> (11.0, 22.0)

# keyword form, and kwargs override the mapping for the same key
evaluate("{A} - {B}", A=[10.0, 20.0], B=[3.0, 5.0])
# -> (7.0, 15.0)
```

Signature:

```python
def evaluate(
    formula: str,
    parameters: Mapping[str, Sequence[float | int]] | None = None,
    **kwargs: Sequence[float | int],
) -> tuple[float, ...]: ...
```

### Formula syntax

Formulas are plain text with `{NAME}` placeholders substituted by parameter series. Supported grammar (a strict, safe subset of Python expressions — parsed via `ast` and validated against an explicit allow-list, so nothing outside this list, including unknown function calls, attribute access, subscripting, or comprehensions, is accepted):

| Category | Supported |
|---|---|
| Placeholders | `{NAME}` — letters, digits, underscore; must start with a letter or underscore |
| Arithmetic | `+`  `-`  `*`  `/`  `%`  `**`, unary `+x` / `-x`, and parentheses |
| Comparisons | `==`  `!=`  `<`  `<=`  `>`  `>=` (chainable, e.g. `0 <= {A} < 100`) |
| Boolean | `and`, `or` |
| Conditional | ternary `X if COND else Y` |
| Functions | `rolling_average(series, N)` — simple moving average of the last `N` aligned points (NaNs skipped); see [Rolling average](#rolling-average) |
| Constants | numeric literals only: `42`, `3.14`, `1e-3`. No strings, booleans, `None`, lists, etc. |

Whitespace (including newlines/tabs) is normalized before parsing, so multi-line formulas are fine.

**Evaluation semantics:**

- Non-conditional formulas are evaluated **vectorized** (whole series at once) for speed.
- Formulas containing a comparison, `and`/`or`, or a ternary are evaluated **element-by-element**, and only the branch selected for that element is evaluated. This means a division-by-zero (or other value-dependent failure) in the branch *not* taken for a given element never raises — this is the standard pattern for guarding divisions:
  ```python
  evaluate("{A} / {B} if {B} != 0 else 0", {"A": [10.0, 20.0], "B": [2.0, 0.0]})
  # -> (5.0, 0.0)   # second element never attempts 20.0 / 0.0
  ```
- If every referenced parameter is an empty sequence, the result is `()` — not an error.
- Value-dependent arithmetic failures (division/modulo by zero, exponent overflow) are raised as native `ZeroDivisionError` / `OverflowError`, **not** wrapped — only structural problems raise `FormulaError` subclasses.
- Compiled formulas are cached (`lru_cache`, keyed on normalized text) and constant-only subtrees (e.g. `24 * 3600`) are folded once at compile time, so repeated evaluation of the same formula string is cheap.

### Rolling average

`rolling_average(series, N)` is a simple moving average (not time-weighted, and not a CDF `aggregate_type="average"`). `N` is a positive integer constant (literals and folded expressions like `12 * 2` or `6 / 2` are fine; a parameter `{WINDOW}` is not). The series argument can be any numeric sub-expression.

The result is **the same length as the inputs**. At the start of a series there are fewer than `N` points, so those indexes average whatever finite values exist so far (index 0 is itself; the true `N`-point average starts at index `N - 1`). `NaN` entries are skipped in the window; a window with no finite values is `NaN`. After `Calculator` drops those empty windows on the time-grid path (see below), `inputs[alias][i]` still corresponds to `datapoints[i]`.

```python
evaluate("rolling_average({A}, 3)", {"A": [10.0, 20.0, 30.0, 40.0]})
# -> (10.0, 15.0, 20.0, 30.0)

evaluate(
    "rolling_average({A}, 3) - {B}",
    {"A": [10.0, 20.0, 30.0, 40.0], "B": [1.0, 2.0, 3.0, 4.0]},
)
# -> (9.0, 13.0, 17.0, 26.0)
```

`evaluate()` is always **count-based**: last `N` values in the sequences you pass. `Calculator` is count-based too unless every time-series parameter is a uniform CDF aggregate *and* the formula calls `rolling_average` — then it fills the bucket grid first.

#### When `Calculator` stays count-based

The query is aligned as usual (`intersect` or `strict`), then `rolling_average` runs over those surviving points. Gaps in time are not inserted.

| Case | What happens |
|---|---|
| `evaluate(...)` | Last `N` values in the arrays you pass. No timestamps. |
| Raw series (no `aggregate_type` / `granularity`) | Last `N` retrieved points. A 4-minute hole between samples still counts as one step. |
| Mixed granularities (e.g. `1m` and `5m`) | Same: last `N` aligned points, no calendar fill. |
| Any time-series parameter is empty | No fill. Then `intersect` yields an empty result; `strict` raises if another series has points. |
| Formula has no `rolling_average` call | Aggregates are **not** filled. `{A} + {B}` stays timestamp intersection. |
| Granularity cannot be parsed / grid is empty | Falls back to the align path above. |

Same minute sums at `t0,t1,t2` then a gap then `t6,t7,t8` (`10, 20, 30, 100, 110, 120`):

```text
rolling_average({A}, 3)  ->  10, 15, 20, 50, 80, 110
```

`50` is `(20+30+100)/3` — the window jumped the hole.

#### When `Calculator` fills a time grid

All of these must hold:

1. Every time-series parameter has an `aggregate_type` and the **same** `granularity` (constants do not count).
2. Every one of those series is non-empty.
3. The formula contains a `rolling_average(...)` call (nested is fine).
4. A bucket grid can be built.

Then each series is expanded onto every bucket that **overlaps** `[start, end)`. Missing buckets become `NaN` in `inputs` and are skipped inside the window, so `rolling_average({GQ}, 3)` on minute sums is “last 3 minutes that have data.” After evaluation, timestamps whose **formula** result is `NaN` are omitted from `datapoints` and `inputs`.

Same data as above, `granularity="1m"`, window `[t0, t9)`:

```text
inputs GQ:     10, 20, 30, NaN, NaN, NaN, 100, 110, 120     (t0..t8)
rolling avg 3: 10, 15, 20,  25,  30,  — , 100, 105, 110
```

`t5` is dropped (window `t3..t5` is all `NaN`). `t3` is `25` = `(20+30)/2`. `t6` is `100` (only the new sample). That is the difference from count-based `50` at the first post-gap point.

| Case | What happens |
|---|---|
| Hole in the middle | Filled with `NaN`, skipped in the window; later buckets still see earlier finite values that fall inside `N` steps. |
| Trailing buckets after the last sample | Partial windows keep emitting until the window is all `NaN`. |
| CDF bucket starts before `start` | Kept when that bucket still overlaps `[start, end)` (e.g. `start` mid-minute with `1m`, or midday `start` with a local `1d`). It appears in `datapoints` and participates in later windows. |
| Bucket ends exactly at `start` | Not on the grid (`[start, end)`). |
| Second series missing at a filled gap | `{A}` may still have a rolling value; `{A} - {B}` is `NaN` there and that index is dropped. `{A}`'s value at that bucket still sits in later windows. |
| Constant in the formula | Broadcast onto the full grid, so `rolling_average({GQ}, 3) - {C}` keeps the filled minutes. |
| `alignment="intersect"` (default) | Fill **replaces** intersection. Series are not intersected first (that would throw away a value that only one series has, then put `NaN` on both sides). |
| `alignment="strict"` | Retrieved timestamps must already match or `ParameterTimestampError` is raised. Matching series are still expanded onto the calendar grid (shared holes become `NaN`). |
| `timezone=` | Hour and longer grids follow that local calendar (DST, month length), same as CDF retrieve. Sub-hour grids are fixed UTC durations; `timezone` does not change them. |
| Lookback | Retrieve is still `[start, end]` only. The first `N - 1` result points are a warmup; pass an earlier `start` if you need a full window at the beginning of the range you care about. |

Unknown function names, keyword arguments, starred arguments, and a non-constant or non-positive window still raise `InvalidFormulaError`.

A ternary (or `and`/`or`) around the **call** does not protect neighbors in the window of a selected index. Put the guard **inside** the series argument. A call that is never selected does not run. Indexes that do not select the call, and are not in a selected window, are not evaluated.

```python
evaluate(
    "rolling_average({A} / {B} if {B} != 0 else 0, 2)",
    {"A": [10.0, 20.0, 30.0], "B": [2.0, 0.0, 5.0]},
)
# -> (5.0, 2.5, 3.0)   # the zero is replaced before the window sees it

evaluate(
    "rolling_average({A} / {B}, 2) if {C} > 0 else 0",
    {"A": [10.0, 20.0], "B": [5.0, 0.0], "C": [1.0, 0.0]},
)
# -> (2.0, 0.0)   # index 0's window is only [0]; index 1 never selects the call

evaluate(
    "rolling_average({A} / {B}, 2) if {B} != 0 else 0",
    {"A": [10.0, 20.0, 30.0], "B": [2.0, 0.0, 5.0]},
)
# raises ZeroDivisionError — index 2 selects the call; window [1, 2] includes B == 0

evaluate(
    "rolling_average({A} / {B}, 2) if {C} > 0 else 0",
    {"A": [10.0, 20.0], "B": [0.0, 0.0], "C": [0.0, 0.0]},
)
# -> (0.0, 0.0)   # the call is never selected
```

```python
evaluate(
    "rolling_average({TEMP}, 24) - {SETPOINT}",
    {
        "TEMP": [100.0, 110.0, 120.0, 130.0],
        "SETPOINT": [105.0, 105.0, 110.0, 115.0],
    },
)
# -> (-5.0, 0.0, 0.0, 0.0)
# rolling_average(TEMP, 24) with only 4 points is the expanding mean:
# (100.0, 105.0, 110.0, 115.0)
```

### Errors

Every exception the package raises derives from `CalculatorError`, so `except CalculatorError` catches the lot:

```
CalculatorError                     industrial_model.calculator (re-exported at package root)
├── DatapointsRetrievalError        industrial_model.calculator.exceptions
└── FormulaError                    industrial_model.calculator.formula_expression.exceptions
    ├── InvalidFormulaError
    ├── MissingParameterError
    └── ParameterError
        ├── ParameterLengthError
        ├── ParameterTimestampError
        └── MissingTimeAxisError
```

`DatapointsRetrievalError` covers CDF responses the retriever can't use: a short response, non-numeric datapoints, or a timestamp/value length mismatch. An invalid ``timezone=`` is not wrapped — the Cognite SDK / API error is raised as-is.

The structural formula errors:

| Exception | Raised when |
|---|---|
| `InvalidFormulaError` | Empty formula, invalid/unresolved placeholder syntax, invalid Python syntax, or an unsupported AST node/identifier/constant type (e.g. calling an unknown function, using a string literal, or a non-constant / non-positive `rolling_average` window). |
| `MissingParameterError` | The formula references a placeholder with no matching entry in `parameters`/`kwargs`. |
| `ParameterError` | A supplied parameter value isn't a numeric sequence (e.g. a string, or a sequence containing non-numeric/boolean items). |
| `ParameterLengthError` | Two or more referenced parameters have different lengths (and not all are empty). Direct `evaluate()` calls raise this; `Calculator` aligns on timestamps before calling `evaluate`. |
| `ParameterTimestampError` | A `CalculatorQuery` with `alignment="strict"` has time-series parameters that do not share the same timestamps at every index. |
| `MissingTimeAxisError` | A `CalculatorQuery` has parameters but none of them are time-series parameters, so there are no timestamps to broadcast its constants onto. |

Value-dependent failures (`ZeroDivisionError`, `OverflowError`) are intentionally left unwrapped as native Python exceptions.

---

## Examples

### Simple

```python
evaluate("{A} + {B}", {"A": [1.0, 2.0], "B": [3.0, 4.0]})
# -> (4.0, 6.0)

evaluate("{APV} / {HEADCOUNT}", {"APV": [100.0], "HEADCOUNT": [4.0]})
# -> (25.0,)

evaluate("(24 * 3600) - {LLOEE}", {"LLOEE": [10.0, 20.0]})
# -> (86390.0, 86380.0)
```

### Guarding division by zero (element-wise ternary)

```python
evaluate(
    "{A} / {B} if {B} != 0 else 0",
    {"A": [10.0, 20.0, 30.0], "B": [2.0, 0.0, 5.0]},
)
# -> (5.0, 0.0, 6.0)
```

### Complex, real-world style formulas

Unit conversion mixing metric and imperial components (kilograms + pounds-to-kg):

```python
evaluate(
    "{A1KG} + ({A1LBS} * 453592)",
    {"A1KG": [10.0], "A1LBS": [2.0]},
)
```

A multi-term OEE/scrap-rate style formula combining several conversions, guards, and a weighted ratio:

```python
formula = (
    "100 * ({AEKG}+{A0KG}+(({AELBS}+{A0LBS})*0.453592)) "
    "/ ({AEKG}+{A0KG}+{A1KG}+{R1KG}+{R2KG}+{R3KG}"
    "+(({AELBS}+{A0LBS}+{A1LBS}+{R1LBS}+{R2LBS}+{R3LBS})*0.453592))"
)
evaluate(formula, {
    "AEKG": [1.0], "A0KG": [2.0], "A1KG": [3.0],
    "R1KG": [4.0], "R2KG": [5.0], "R3KG": [6.0],
    "AELBS": [1.0], "A0LBS": [2.0], "A1LBS": [3.0],
    "R1LBS": [4.0], "R2LBS": [5.0], "R3LBS": [6.0],
})
```

Chained comparisons combined with boolean operators, nested inside a ternary — evaluated purely element-by-element so out-of-range or zero-denominator elements never touch the unsafe branch:

```python
evaluate(
    "({VALUE} / {TOTAL}) if ({TOTAL} > 0 and 0 <= {VALUE} <= {TOTAL}) else -1",
    {"VALUE": [5.0, 15.0, -1.0], "TOTAL": [10.0, 0.0, 10.0]},
)
# -> (0.5, -1.0, -1.0)   # 15/0 and -1/10 both short-circuit to the -1 branch
```

Deeply parenthesized, multi-parameter net calculation (Overall Equipment Effectiveness style downtime budget):

```python
evaluate(
    "(24*3600) - {LLOEE} - {ALOEE} - {PLOEE} - {QLOEE}",
    {
        "LLOEE": [100.0, 200.0],
        "ALOEE": [50.0, 75.0],
        "PLOEE": [25.0, 30.0],
        "QLOEE": [10.0, 15.0],
    },
)
# -> (86215.0, 86080.0)
```

### End-to-end with `Calculator`, aggregates, and multiple queries

```python
from datetime import datetime, timedelta, UTC
from industrial_model.calculator import Calculator, CalculatorQuery, TimeSeriesParameter
from industrial_model.models import InstanceId

end = datetime.now(tz=UTC)
start = end - timedelta(days=7)

# Hourly-average temperature vs. raw setpoint, combined into a deviation formula,
# guarded against a zero setpoint.
temp = TimeSeriesParameter(
    alias="TEMP",
    timeseries_instance_id=InstanceId(space="plant", external_id="ts_temp"),
    aggregate_type="average",
    granularity="1h",
)
setpoint = TimeSeriesParameter(
    alias="SETPOINT",
    timeseries_instance_id=InstanceId(space="plant", external_id="ts_setpoint"),
    aggregate_type="average",
    granularity="1h",
)

deviation_query = CalculatorQuery(
    formula="(({TEMP} - {SETPOINT}) / {SETPOINT}) * 100 if {SETPOINT} != 0 else 0",
    parameters=[temp, setpoint],
)

# A second, unrelated formula reusing {TEMP} in the same batch: fetched once, used twice.
raw_query = CalculatorQuery(formula="{TEMP} * 1.8 + 32", parameters=[temp])

deviation_result, fahrenheit_result = await calculator.calculate_multiples(
    [deviation_query, raw_query], start, end
)
```

### Constants combined with multiple reduced time series

Total plant output across three production lines (summed hourly), converted from kilograms
to pounds via a constant, then compared against a fixed daily target:

```python
from industrial_model.calculator import (
    Calculator, CalculatorQuery, ConstantParameter, MultiTimeSeriesParameter,
)
from industrial_model.models import InstanceId

lines_kg = MultiTimeSeriesParameter(
    alias="LINES_KG",
    timeseries_instance_ids=[
        InstanceId(space="plant", external_id="ts_line_1"),
        InstanceId(space="plant", external_id="ts_line_2"),
        InstanceId(space="plant", external_id="ts_line_3"),
    ],
    aggregate_type="sum",
    granularity="1h",
    reducer="sum",
)
kg_to_lbs = ConstantParameter(alias="KG_TO_LBS", value=2.20462)
target_lbs = ConstantParameter(alias="TARGET_LBS", value=5000.0)

query = CalculatorQuery(
    formula="(({LINES_KG} * {KG_TO_LBS}) / {TARGET_LBS}) * 100",
    parameters=[lines_kg, kg_to_lbs, target_lbs],
)

result = await calculator.calculate(query, start, end)
# one DataPoint per hour with data in common across all three lines;
# each value is the combined, converted output as a % of target.
```

---

## Architecture reference

| File | Responsibility |
|---|---|
| `calculator.py` | `Calculator` — async orchestrator for retrieval + evaluation of one or many queries. Takes a `CogniteClient` and uses `get_async_client()` for CDF I/O. Splits `ConstantParameter`s (broadcast, never fetched) from time-series parameters (fetched via `DatapointsRetriever`), uses `SeriesReducer` to collapse a `MultiTimeSeriesParameter`'s series, then aligns remaining time-series parameters (`intersect` by default, or `strict`). When `rolling_average` runs over a uniform aggregate granularity, fills that bucket grid before evaluation after honoring `alignment`. |
| `_timing.py` | `StageTimer` — exclusive wall-clock timings for DEBUG stage summaries. No-op when the calculator logger is not at DEBUG. |
| `_timezone.py` | Resolves IANA / UTC-offset strings to ``tzinfo`` when stepping hour+ rolling-average grids. Public ``timezone=`` is not validated here. |
| `_grid.py` | Bucket-grid construction for `rolling_average` over a uniform CDF granularity (fixed steps for sub-hour; local calendar for hour+). |
| `datapoints_retrieval.py` | `DatapointsRetriever` — fetching only: builds deduplicated `DatapointsQuery` requests per unique (time series, aggregate, granularity), retrieves them in one SDK call (and asks again when a page is long enough to be truncated), and parses responses into `(timestamp, value)` pairs (dropping `None` values). Returns one *unreduced* series per instance id — combining them is the caller's job. Optional retrieve ``timezone`` is applied to every aggregate in the batch (omitted from the query when unset). |
| `series_reducer.py` | `SeriesReducer` — timestamp intersection via a sorted k-way merge. `reduce` combines several series into one with `min`/`max`/`sum`/`average`; `align` filters several series onto their common timestamps. Both normalize every input first (sort by timestamp, collapse duplicate timestamps to their last value), including the single-series case, so output never depends on how many series were passed. Used by `Calculator` for `MultiTimeSeriesParameter` and for formula-level `intersect` alignment. |
| `models.py` | Query models are Pydantic: `CalculatorParameter` (discriminated union), `ConstantParameter`, `TimeSeriesParameter`, `MultiTimeSeriesParameter`, `TimeSeriesParameterBase` (shared fields, not itself part of the union), `ReducerType`, `AlignmentMode`, `Series` (the `list[(timestamp, value)]` alias used throughout), `CalculatorQuery` (validates unique parameter aliases). Output types are not Pydantic — validation per datapoint was the assemble bottleneck — so `DataPoint` is a `NamedTuple` and `CalculationResult` is a frozen dataclass. |
| `exceptions.py` | `CalculatorError`, the root every other exception in the package derives from, and `DatapointsRetrievalError` for unusable CDF responses. |
| `formula_expression/core.py` | Public `evaluate()` entry point; merges positional mapping + kwargs. |
| `formula_expression/_compiler.py` | Text normalization, placeholder substitution, AST allow-list validation (including allow-listed `Call`s), constant folding, `lru_cache`-based compile caching. |
| `formula_expression/_functions.py` | Allow-listed formula functions: name, arity, and implementation. Currently `rolling_average` (same-length simple moving average with a partial prefix; NaNs skipped). |
| `formula_expression/_evaluator.py` | AST walker: vectorized evaluation for pure-arithmetic trees (including function calls), index-by-index short-circuiting evaluation for conditional/boolean/comparison trees. |
| `formula_expression/_runtime.py` | Binds compiled formulas to concrete parameter values: parameter presence/type/length validation, then delegates to the evaluator. |
| `formula_expression/exceptions.py` | `FormulaError` (a `CalculatorError`) and its subclasses, including the two errors `Calculator` itself raises: `ParameterTimestampError` (`alignment` is `strict` and time-series parameters don't share timestamps) and `MissingTimeAxisError` (the query has no time-series parameter). |
