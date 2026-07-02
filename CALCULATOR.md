# Calculator

The `industrial_model.calculator` package computes derived time series from raw Cognite Data Fusion (CDF) datapoints. You describe a formula using `{PLACEHOLDER}` parameters, point each placeholder at a CDF time series (raw or aggregated), and the calculator fetches the datapoints, aligns them, and evaluates the formula element-by-element.

It's built from two layers:

- **`Calculator`** — the CDF-facing layer. Resolves `CalculatorQuery` objects into datapoint requests, retrieves and deduplicates them via `CogniteClient`, and evaluates the formula over the results.
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
from industrial_model.calculator import Calculator, CalculatorParameter, CalculatorQuery
from industrial_model.models import InstanceId

client = CogniteClient()
calculator = Calculator(client)

query = CalculatorQuery(
    formula="{PRODUCED} - {SCRAP}",
    parameters=[
        CalculatorParameter(
            alias="PRODUCED",
            timeseries_instance_id=InstanceId(space="my-space", external_id="ts_produced"),
        ),
        CalculatorParameter(
            alias="SCRAP",
            timeseries_instance_id=InstanceId(space="my-space", external_id="ts_scrap"),
        ),
    ],
)

end = datetime.now(tz=UTC)
start = end - timedelta(days=1)

result = calculator.calculate(query, start, end)
# result.query:      CalculatorQuery  (the query that produced this result)
# result.datapoints: list[DataPoint], each with .timestamp: datetime and .value: float

for dp in result.datapoints:
    print(dp.timestamp, dp.value)
```

`result.query` is the exact `CalculatorQuery` that was passed in — handy when matching results back to their originating query after `calculate_multiples`.

Each `DataPoint.timestamp` comes from the **first parameter** listed in the query (`query.parameters[0]`) — every other parameter's series must line up with it one-to-one, or evaluation raises `ParameterLengthError`. Two datapoints "line up" if they occupy the same index after retrieval, so all parameters in a query should share the same time range and granularity.

### Batching multiple queries

Use `calculate_multiples` when you need several formulas evaluated over the same window. All parameters across all queries are fetched in a single retrieval pass, and identical time series requests (same instance id, aggregate, and granularity) are deduplicated to one CDF call, even across different queries:

```python
results = calculator.calculate_multiples(
    [
        CalculatorQuery(formula="{A} + {B}", parameters=[param_a, param_b]),
        CalculatorQuery(formula="{A} * 2", parameters=[param_a]),  # {A} reused, not refetched
    ],
    start,
    end,
)
# results[0], results[1] -> CalculationResult, one per input query, same order
```

---

## Data models

```python
from industrial_model.calculator import (
    CalculatorParameter,
    CalculatorQuery,
    CalculationResult,
    DataPoint,
)
```

| Model | Fields | Notes |
|---|---|---|
| `CalculatorParameter` | `alias: str`, `timeseries_instance_id: InstanceId`, `aggregate_type: Aggregate \| None`, `granularity: str \| None` | `alias` is the name used inside `{...}` placeholders in the formula. |
| `CalculatorQuery` | `formula: str`, `parameters: list[CalculatorParameter]` | One query = one formula + the parameters it references. |
| `DataPoint` | `timestamp: datetime`, `value: float` | A single evaluated point. |
| `CalculationResult` | `query: CalculatorQuery`, `datapoints: list[DataPoint]` | Output of `Calculator.calculate`. `query` is the originating query; `datapoints` has one `DataPoint` per aligned index across the query's parameters. |

**Raw vs. aggregated parameters:**

- Leave `aggregate_type=None` to fetch raw datapoints for the time series.
- Set `aggregate_type` (e.g. `"average"`, `"sum"`, `"max"`, `"min"`, `"count"`, ...) to fetch a CDF aggregate. `granularity` (e.g. `"1h"`, `"1d"`) is **required** whenever `aggregate_type` is set — `Calculator` raises `ValueError` otherwise.

```python
from cognite.client.data_classes.datapoint_aggregates import Aggregate

CalculatorParameter(
    alias="AVG_TEMP",
    timeseries_instance_id=InstanceId(space="my-space", external_id="ts_temp"),
    aggregate_type="average",  # or Aggregate.average
    granularity="1h",
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

Formulas are plain text with `{NAME}` placeholders substituted by parameter series. Supported grammar (a strict, safe subset of Python expressions — parsed via `ast` and validated against an explicit allow-list, so nothing outside this list, including function calls, attribute access, subscripting, or comprehensions, is accepted):

| Category | Supported |
|---|---|
| Placeholders | `{NAME}` — letters, digits, underscore; must start with a letter or underscore |
| Arithmetic | `+`  `-`  `*`  `/`  `%`  `**`, unary `+x` / `-x`, and parentheses |
| Comparisons | `==`  `!=`  `<`  `<=`  `>`  `>=` (chainable, e.g. `0 <= {A} < 100`) |
| Boolean | `and`, `or` |
| Conditional | ternary `X if COND else Y` |
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

### Errors

All structural errors are subclasses of `industrial_model.calculator.formula_expression.exceptions.FormulaError`:

| Exception | Raised when |
|---|---|
| `InvalidFormulaError` | Empty formula, invalid/unresolved placeholder syntax, invalid Python syntax, or an unsupported AST node/identifier/constant type (e.g. calling a function, using a string literal). |
| `MissingParameterError` | The formula references a placeholder with no matching entry in `parameters`/`kwargs`. |
| `ParameterError` | A supplied parameter value isn't a numeric sequence (e.g. a string, or a sequence containing non-numeric/boolean items). |
| `ParameterLengthError` | Two or more referenced parameters have different lengths (and not all are empty). |

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
from industrial_model.calculator import Calculator, CalculatorParameter, CalculatorQuery
from industrial_model.models import InstanceId

end = datetime.now(tz=UTC)
start = end - timedelta(days=7)

# Hourly-average temperature vs. raw setpoint, combined into a deviation formula,
# guarded against a zero setpoint.
temp = CalculatorParameter(
    alias="TEMP",
    timeseries_instance_id=InstanceId(space="plant", external_id="ts_temp"),
    aggregate_type="average",
    granularity="1h",
)
setpoint = CalculatorParameter(
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

deviation_result, fahrenheit_result = calculator.calculate_multiples(
    [deviation_query, raw_query], start, end
)
```

---

## Architecture reference

| File | Responsibility |
|---|---|
| `calculator.py` | `Calculator` — orchestrates retrieval + evaluation for one or many queries. |
| `datapoints_retrieval.py` | `DatapointsRetriever` — builds deduplicated `DatapointsQuery` requests per unique (time series, aggregate, granularity) and parses CDF responses into `(timestamp, value)` pairs, dropping `None` values. |
| `models.py` | Pydantic models: `CalculatorParameter`, `CalculatorQuery`, `CalculationResult`, `DataPoint`, `TimeSeriesParameter`. |
| `formula_expression/core.py` | Public `evaluate()` entry point; merges positional mapping + kwargs. |
| `formula_expression/_compiler.py` | Text normalization, placeholder substitution, AST allow-list validation, constant folding, `lru_cache`-based compile caching. |
| `formula_expression/_evaluator.py` | AST walker: vectorized evaluation for pure-arithmetic trees, index-by-index short-circuiting evaluation for conditional/boolean/comparison trees. |
| `formula_expression/_runtime.py` | Binds compiled formulas to concrete parameter values: parameter presence/type/length validation, then delegates to the evaluator. |
| `formula_expression/exceptions.py` | `FormulaError` hierarchy. |
