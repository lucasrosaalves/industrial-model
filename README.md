# 📦 industrial-model

**Type-safe, Pythonic access to Cognite Data Fusion views.**

`industrial-model` is a Python ORM for Cognite Data Fusion (CDF). Define views as Pydantic models, build queries with a fluent API, and work with CDF in the same way you write the rest of your Python—with types, autocomplete, and clear errors.

```python
from industrial_model import Engine, ViewInstance, ViewInstanceConfig, select
from pathlib import Path

class Asset(ViewInstance):
    view_config = ViewInstanceConfig(
        instance_spaces_prefix="instace_data-",  # Define the scope of your instance spaces to improve performance.
    )
    name: str
    description: str | None = None

engine = Engine.from_config_file(Path("cognite-sdk-config.yaml"))
results = engine.query(select(Asset).limit(10))
# results.data → list[Asset], fully typed
```

---

## ✨ Features

- **Declarative models** — Pydantic-style classes with type hints; only the fields you need
- **Type-safe queries** — Fluent, composable filters with full IDE support
- **Query, search, aggregate** — Standard and paginated queries, full-text search, count/sum/avg/min/max
- **Rich filtering** — Nested queries, edge filters, boolean logic, list/string operators
- **Read and write** — Upsert and delete with edge relationship support
- **Async** — All operations have async equivalents
- **Configurable validation** — Choose how to handle validation errors per request

---

## 📦 Installation

```bash
pip install industrial-model
```

---

## 📚 Table of Contents

| Section | What you'll find |
|--------|-------------------|
| [Getting Started](#-getting-started) | Prerequisites and example schema |
| [Model Definition](#-model-definition) | Views as Pydantic models, aliases, config |
| [Engine Setup](#-engine-setup) | Config file or manual `Engine` / `AsyncEngine` |
| [Querying Data](#-querying-data) | `select()`, pagination, sorting, validation |
| [Filtering](#-filtering) | Comparison, list, string, nested, and edge filters |
| [Search](#-search) | Full-text search with filters |
| [Aggregations](#-aggregations) | Count, sum, avg, min, max, with grouping |
| [Write Operations](#-write-operations) | Upsert and delete |
| [Advanced Features](#-advanced-features) | ID generation, `InstanceId`, result helpers |
| [Async Operations](#-async-operations) | `AsyncEngine` and async API |

---

## 🚀 Getting Started

The quick example above shows the core flow: **model → engine → query**. The rest of this guide uses the `CogniteAsset` view from the `CogniteCore` data model (version `v1`).

### Sample GraphQL Schema

```graphql
type CogniteAsset {
  name: String
  description: String
  tags: [String]
  aliases: [String]
  parent: CogniteAsset
  root: CogniteAsset
}
```

---

## 🏗️ Model Definition

Models map CDF views to Python classes. Inherit from `ViewInstance` (or `WritableViewInstance` for writes) and declare only the properties you need.

### Basic Model

Define your model by inheriting from `ViewInstance` and adding only the properties you need:

```python
from industrial_model import ViewInstance

class CogniteAsset(ViewInstance):
    name: str
    description: str
    aliases: list[str]
```

### Model with Relationships

Include nested relationships by referencing other models:

```python
from industrial_model import ViewInstance

class CogniteAsset(ViewInstance):
    name: str
    description: str
    aliases: list[str]
    parent: CogniteAsset | None = None
    root: CogniteAsset | None = None
```

### Field Aliases

Use Pydantic's `Field` to map properties to different names in CDF:

```python
from pydantic import Field
from industrial_model import ViewInstance

class CogniteAsset(ViewInstance):
    asset_name: str = Field(alias="name")  # Maps to "name" in CDF
    asset_description: str = Field(alias="description")
```

### View Configuration

Configure view mapping and space filtering:

```python
from industrial_model import ViewInstance, ViewInstanceConfig

class CogniteAsset(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="CogniteAsset",  # Maps this class to the 'CogniteAsset' view
        instance_spaces_prefix="Industr-",  # Filters queries to spaces with this prefix
        # OR use explicit spaces:
        # instance_spaces=["Industrial-Data", "Industrial-Production"],
        view_code="ASSET",  # Optional: prefix for ID generation
    )
    name: str
    description: str
    aliases: list[str]
```

### Writable Models

For write operations, inherit from `WritableViewInstance` and implement `edge_id_factory`:

```python
from industrial_model import WritableViewInstance, InstanceId, ViewInstanceConfig

class CogniteAsset(WritableViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    aliases: list[str]
    parent: CogniteAsset | None = None

    def edge_id_factory(self, target_node: InstanceId, edge_type: InstanceId) -> InstanceId:
        """Generate edge IDs for relationships."""
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )
```

### Aggregated Models

For aggregation queries, use `AggregatedViewInstance`:

```python
from industrial_model import AggregatedViewInstance, ViewInstanceConfig

class CogniteAssetByName(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    # The 'value' field is automatically included for aggregation results
```

---

## ⚙️ Engine Setup

The engine connects to CDF and knows which data model and version to use. You can load it from a config file or build it from an existing `CogniteClient`.

### Option A: From Configuration File

Create a `cognite-sdk-config.yaml` file:

```yaml
cognite:
  project: "${CDF_PROJECT}"
  client_name: "${CDF_CLIENT_NAME}"
  base_url: "https://${CDF_CLUSTER}.cognitedata.com"
  credentials:
    client_credentials:
      token_url: "${CDF_TOKEN_URL}"
      client_id: "${CDF_CLIENT_ID}"
      client_secret: "${CDF_CLIENT_SECRET}"
      scopes: ["https://${CDF_CLUSTER}.cognitedata.com/.default"]

data_model:
  external_id: "CogniteCore"
  space: "cdf_cdm"
  version: "v1"
```

```python
from industrial_model import Engine
from pathlib import Path

engine = Engine.from_config_file(Path("cognite-sdk-config.yaml"))
```

### Option B: Manual Setup

```python
from cognite.client import CogniteClient
from industrial_model import Engine, DataModelId

# Create your CogniteClient with appropriate authentication
cognite_client = CogniteClient(
    # ... your client configuration
)

engine = Engine(
    cognite_client=cognite_client,
    data_model_id=DataModelId(
        external_id="CogniteCore",
        space="cdf_cdm",
        version="v1"
    )
)
```

### Async Engine

For async operations, use `AsyncEngine`:

```python
from industrial_model import AsyncEngine
from pathlib import Path

async_engine = AsyncEngine.from_config_file(Path("cognite-sdk-config.yaml"))
```

---

## 🔎 Querying Data

Use `select()` to build statements, then run them with `engine.query()` or `engine.query_all_pages()`. Results are typed and paginated.

### Basic Query

```python
from industrial_model import select

statement = select(CogniteAsset).limit(100)
results = engine.query(statement)

# results is a PaginatedResult with:
# - results.data: list of instances
# - results.has_next_page: bool
# - results.next_cursor: str | None
```

### Query All Pages

Fetch all results across multiple pages:

```python
statement = select(CogniteAsset).limit(1000)
all_results = engine.query_all_pages(statement)  # Returns list[TViewInstance]
```

### Pagination with Cursor

```python
# First page
statement = select(CogniteAsset).limit(100)
page1 = engine.query(statement)

# Next page using cursor
if page1.has_next_page:
    statement = select(CogniteAsset).limit(100).cursor(page1.next_cursor)
    page2 = engine.query(statement)
```

### Sorting

```python
from industrial_model import select

# Ascending order
statement = select(CogniteAsset).asc(CogniteAsset.name)

# Descending order
statement = select(CogniteAsset).desc(CogniteAsset.name)

# Multiple sort fields
statement = (
    select(CogniteAsset)
    .asc(CogniteAsset.name)
    .desc(CogniteAsset.external_id)
)
```

### Validation Modes

Control how validation errors are handled:

```python
# Raise on error (default)
results = engine.query(statement, validation_mode="raiseOnError")

# Ignore validation errors
results = engine.query(statement, validation_mode="ignoreOnError")
```

---

## 🔍 Filtering

Add `.where(...)` to narrow results. Use `col()` for operators like `in_()`, `prefix()`, and `nested_()`; use `==`, `!=`, `&`, and `|` where they apply.

### Comparison Operators

```python
from industrial_model import select, col

# Equality
statement = select(CogniteAsset).where(CogniteAsset.name == "My Asset")
# or
statement = select(CogniteAsset).where(col(CogniteAsset.name).equals_("My Asset"))

# Inequality
statement = select(CogniteAsset).where(CogniteAsset.name != "My Asset")

# Less than / Less than or equal
statement = select(CogniteAsset).where(col(CogniteAsset.external_id).lt_("Z"))
statement = select(CogniteAsset).where(col(CogniteAsset.external_id).lte_("Z"))

# Greater than / Greater than or equal
statement = select(CogniteAsset).where(col(CogniteAsset.external_id).gt_("A"))
statement = select(CogniteAsset).where(col(CogniteAsset.external_id).gte_("A"))
```

### List Operators

```python
from industrial_model import select, col

# In (matches any value in list)
statement = select(CogniteAsset).where(
    col(CogniteAsset.external_id).in_(["asset-1", "asset-2", "asset-3"])
)

# Contains any (for array fields)
statement = select(CogniteAsset).where(
    col(CogniteAsset.aliases).contains_any_(["alias1", "alias2"])
)

# Contains all (for array fields)
statement = select(CogniteAsset).where(
    col(CogniteAsset.tags).contains_all_(["tag1", "tag2"])
)
```

### String Operators

```python
from industrial_model import select, col

# Prefix matching
statement = select(CogniteAsset).where(
    col(CogniteAsset.name).prefix("Pump-")
)
```

### Existence Operators

```python
from industrial_model import select, col

# Field exists
statement = select(CogniteAsset).where(
    col(CogniteAsset.description).exists_()
)

# Field does not exist
statement = select(CogniteAsset).where(
    col(CogniteAsset.description).not_exists_()
)

# Using == and != with None
statement = select(CogniteAsset).where(
    CogniteAsset.parent == None  # Field is null
)
statement = select(CogniteAsset).where(
    CogniteAsset.parent != None  # Field is not null
)
```

### Nested Queries

Filter by properties of related instances:

```python
from industrial_model import select, col

# Filter by parent's name
statement = select(CogniteAsset).where(
    col(CogniteAsset.parent).nested_(
        col(CogniteAsset.name) == "Parent Asset Name"
    )
)

# Multiple nested conditions
statement = select(CogniteAsset).where(
    col(CogniteAsset.parent).nested_(
        (col(CogniteAsset.name) == "Parent Asset") &
        (col(CogniteAsset.external_id).prefix("PARENT-"))
    )
)
```

### Boolean Operators

Combine filters using `&`, `|`, and boolean functions:

```python
from industrial_model import select, col, and_, or_, not_

# Using & (AND) operator
statement = select(CogniteAsset).where(
    (col(CogniteAsset.name).prefix("Pump-")) &
    (col(CogniteAsset.aliases).contains_any_(["pump"]))
)

# Using | (OR) operator
statement = select(CogniteAsset).where(
    (col(CogniteAsset.name) == "Asset 1") |
    (col(CogniteAsset.name) == "Asset 2")
)

# Using and_() function
statement = select(CogniteAsset).where(
    and_(
        col(CogniteAsset.aliases).contains_any_(["my_alias"]),
        col(CogniteAsset.description).exists_(),
    )
)

# Using or_() function
statement = select(CogniteAsset).where(
    or_(
        col(CogniteAsset.name) == "Asset 1",
        col(CogniteAsset.name) == "Asset 2",
        col(CogniteAsset.name) == "Asset 3",
    )
)

# Using not_() function
statement = select(CogniteAsset).where(
    not_(col(CogniteAsset.name).prefix("Test-"))
)

# Complex combinations
statement = select(CogniteAsset).where(
    and_(
        col(CogniteAsset.aliases).contains_any_(["my_alias"]),
        or_(
            col(CogniteAsset.parent).nested_(
                col(CogniteAsset.name) == "Parent Asset Name 1"
            ),
            col(CogniteAsset.parent).nested_(
                col(CogniteAsset.name) == "Parent Asset Name 2"
            ),
        ),
    )
)
```

### Edge Filtering

Filter on edge properties using `where_edge`:

```python
from industrial_model import select, col

# Filter by edge properties
statement = (
    select(CogniteAsset)
    .where_edge(
        CogniteAsset.parent,
        col(CogniteAsset.external_id) == "PARENT-123"
    )
    .limit(100)
)
```

### Date/Time Filtering

```python
from datetime import datetime
from industrial_model import select, col

# Filter by datetime
cutoff_date = datetime(2024, 1, 1)
statement = select(CogniteAsset).where(
    col(CogniteAsset.created_time).gte_(cutoff_date)
)
```

### InstanceId Filtering

Filter using InstanceId objects:

```python
from industrial_model import select, col, InstanceId

parent_id = InstanceId(external_id="PARENT-123", space="cdf_cdm")
statement = select(CogniteAsset).where(
    col(CogniteAsset.parent) == parent_id
)

# Or using nested queries
statement = select(CogniteAsset).where(
    col(CogniteAsset.parent).nested_(
        col(CogniteAsset.external_id) == "PARENT-123"
    )
)
```

---

## 🔍 Search

Full-text search over view instances. Combine `search()` with `.where()` filters and `.query_by()` to search specific properties.

### Search with Filters

```python
from industrial_model import search, col

search_statement = (
    search(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
    .query_by(
        query="pump equipment",
        query_properties=[CogniteAsset.name, CogniteAsset.description],
    )
)

results = engine.search(search_statement)
```

### Search Operators

```python
from industrial_model import search, col

# AND operator (all terms must match)
search_statement = (
    search(CogniteAsset)
    .query_by(
        query="pump equipment",
        query_properties=[CogniteAsset.name],
        operation="AND",
    )
)

# OR operator (any term can match) - default
search_statement = (
    search(CogniteAsset)
    .query_by(
        query="pump equipment",
        query_properties=[CogniteAsset.name],
        operation="OR",
    )
)
```

### Search with Multiple Properties

```python
from industrial_model import search, col

search_statement = (
    search(CogniteAsset)
    .query_by(
        query="industrial pump",
        query_properties=[
            CogniteAsset.name,
            CogniteAsset.description,
            CogniteAsset.external_id,
        ],
        operation="AND",
    )
    .limit(50)
)

results = engine.search(search_statement)
```

---

## 📊 Aggregations

Use `AggregatedViewInstance` and `aggregate()` for count, sum, avg, min, and max—optionally with `.group_by()` and `.where()`.

### Count Aggregation

```python
from industrial_model import aggregate, AggregatedViewInstance, ViewInstanceConfig, col

class CogniteAssetCount(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")

# Simple count
statement = aggregate(CogniteAssetCount, "count")
results = engine.aggregate(statement)
# Each result has a 'value' field with the count

# Count with grouping
class CogniteAssetByName(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str

statement = aggregate(CogniteAssetByName, "count").group_by(
    col(CogniteAssetByName.name)
)
results = engine.aggregate(statement)
# Results grouped by name, each with a count value
```

### Sum Aggregation

```python
from industrial_model import aggregate, AggregatedViewInstance, ViewInstanceConfig, col

class CogniteAssetWithValue(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    # Assume there's a 'value' property in the view

statement = (
    aggregate(CogniteAssetWithValue, "sum")
    .aggregate_by(CogniteAssetWithValue.value)
    .group_by(col(CogniteAssetWithValue.name))
)
results = engine.aggregate(statement)
```

### Average, Min, Max Aggregations

```python
from industrial_model import aggregate, AggregatedViewInstance, ViewInstanceConfig, col

class CogniteAssetStats(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str

# Average
statement = (
    aggregate(CogniteAssetStats, "avg")
    .aggregate_by(CogniteAssetStats.value)
    .group_by(col(CogniteAssetStats.name))
)

# Minimum
statement = (
    aggregate(CogniteAssetStats, "min")
    .aggregate_by(CogniteAssetStats.value)
    .group_by(col(CogniteAssetStats.name))
)

# Maximum
statement = (
    aggregate(CogniteAssetStats, "max")
    .aggregate_by(CogniteAssetStats.value)
    .group_by(col(CogniteAssetStats.name))
)
```

### Aggregation with Filters

```python
from industrial_model import aggregate, AggregatedViewInstance, ViewInstanceConfig, col

class CogniteAssetByName(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str

statement = (
    aggregate(CogniteAssetByName, "count")
    .where(col("description").exists_())
    .group_by(col(CogniteAssetByName.name))
    .limit(100)
)

results = engine.aggregate(statement)
```

### Multiple Group By Fields

```python
from industrial_model import aggregate, AggregatedViewInstance, ViewInstanceConfig, col

class CogniteAssetGrouped(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    space: str

statement = (
    aggregate(CogniteAssetGrouped, "count")
    .group_by(
        col(CogniteAssetGrouped.name),
        col(CogniteAssetGrouped.space),
    )
)

results = engine.aggregate(statement)
```

---

## ✏️ Write Operations

Use `WritableViewInstance` and implement `edge_id_factory` for models with relationships. Then `engine.upsert()` and `engine.delete()` work on lists of instances.

### Upsert Instances

```python
from industrial_model import WritableViewInstance, InstanceId, ViewInstanceConfig, select, col

class CogniteAsset(WritableViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    aliases: list[str]
    parent: CogniteAsset | None = None

    def edge_id_factory(self, target_node: InstanceId, edge_type: InstanceId) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )

# Update existing instances
instances = engine.query_all_pages(
    select(CogniteAsset).where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
)

for instance in instances:
    instance.aliases.append("new_alias")

# Upsert with default options (merge, keep unset fields)
engine.upsert(instances)

# Upsert with replace=True (replace entire instance)
engine.upsert(instances, replace=True)

# Upsert with remove_unset=True (remove fields not set in model)
engine.upsert(instances, remove_unset=True)
```

### Create New Instances

```python
from industrial_model import WritableViewInstance, InstanceId, ViewInstanceConfig

class CogniteAsset(WritableViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    aliases: list[str]

    def edge_id_factory(self, target_node: InstanceId, edge_type: InstanceId) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )

# Create new instances
new_asset = CogniteAsset(
    external_id="NEW-ASSET-001",
    space="cdf_cdm",
    name="New Asset",
    aliases=["alias1", "alias2"],
)

engine.upsert([new_asset])
```

### Delete Instances

```python
from industrial_model import search, col

# Find instances to delete
instances_to_delete = engine.search(
    search(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["old_alias"]))
    .query_by("obsolete", [CogniteAsset.name])
)

# Delete them
engine.delete(instances_to_delete)
```

---

## 🚀 Advanced Features

Utilities for ID generation, `InstanceId` handling, and working with `PaginatedResult`.

### Generate Model IDs

Generate IDs from model fields:

```python
from industrial_model import ViewInstance, ViewInstanceConfig

class CogniteAsset(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="CogniteAsset",
        view_code="ASSET",
    )
    name: str
    space: str

asset = CogniteAsset(
    external_id="",
    space="cdf_cdm",
    name="Pump-001",
    space="Industrial-Data",
)

# Generate ID from name
id_from_name = asset.generate_model_id(["name"])
# Result: "ASSET-Pump-001"

# Generate ID from multiple fields
id_from_fields = asset.generate_model_id(["space", "name"])
# Result: "ASSET-Industrial-Data-Pump-001"

# Without view_code prefix
id_no_prefix = asset.generate_model_id(["name"], view_code_as_prefix=False)
# Result: "Pump-001"

# Custom separator
id_custom = asset.generate_model_id(["space", "name"], separator="_")
# Result: "ASSET-Industrial-Data_Pump-001"
```

### InstanceId Operations

```python
from industrial_model import InstanceId

# Create InstanceId
asset_id = InstanceId(external_id="ASSET-001", space="cdf_cdm")

# Convert to tuple
space, external_id = asset_id.as_tuple()

# Use in comparisons
other_id = InstanceId(external_id="ASSET-001", space="cdf_cdm")
assert asset_id == other_id

# Use as dictionary key (InstanceId is hashable)
id_map = {asset_id: "some_value"}
```

### PaginatedResult Utilities

```python
from industrial_model import select

statement = select(CogniteAsset).limit(100)
result = engine.query(statement)

# Get first item or None
first_asset = result.first_or_default()

# Check if there are more pages
if result.has_next_page:
    next_cursor = result.next_cursor
    # Use cursor for next page
```

---

## ⚡ Async Operations

Use `AsyncEngine` for async code. Every sync method has an `_async` counterpart (e.g. `query_async`, `upsert_async`).

### AsyncEngine Setup

```python
from industrial_model import AsyncEngine
from pathlib import Path

async_engine = AsyncEngine.from_config_file(Path("cognite-sdk-config.yaml"))
```

### Async Query Operations

```python
from industrial_model import select, col

# Async query
statement = select(CogniteAsset).where(col(CogniteAsset.name).prefix("Pump-"))
result = await async_engine.query_async(statement)

# Async query all pages
all_results = await async_engine.query_all_pages_async(statement)

# Async search
search_statement = search(CogniteAsset).query_by("pump")
results = await async_engine.search_async(search_statement)

# Async aggregate
aggregate_statement = aggregate(CogniteAssetByName, "count")
results = await async_engine.aggregate_async(aggregate_statement)
```

### Async Write Operations

```python
# Async upsert
instances = [new_asset1, new_asset2]
await async_engine.upsert_async(instances, replace=False, remove_unset=False)

# Async delete
await async_engine.delete_async(instances_to_delete)
```

### Complete Async Example

```python
import asyncio
from industrial_model import AsyncEngine, select, col
from pathlib import Path

async def main():
    engine = AsyncEngine.from_config_file(Path("cognite-sdk-config.yaml"))
    
    # Run multiple queries concurrently
    statement1 = select(CogniteAsset).where(col(CogniteAsset.name).prefix("Pump-"))
    statement2 = select(CogniteAsset).where(col(CogniteAsset.name).prefix("Valve-"))
    
    results1, results2 = await asyncio.gather(
        engine.query_all_pages_async(statement1),
        engine.query_all_pages_async(statement2),
    )
    
    print(f"Found {len(results1)} pumps and {len(results2)} valves")

asyncio.run(main())
```

---

## 📝 Complete Example

Putting it together: query with filters, search, aggregate, upsert, and delete in one script.

```python
from industrial_model import (
    Engine,
    ViewInstance,
    WritableViewInstance,
    ViewInstanceConfig,
    InstanceId,
    select,
    search,
    aggregate,
    AggregatedViewInstance,
    col,
    and_,
    or_,
)
from pathlib import Path

# Define models
class CogniteAsset(WritableViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="CogniteAsset",
        instance_spaces_prefix="Industrial-",
    )
    name: str
    description: str | None = None
    aliases: list[str] = []
    parent: CogniteAsset | None = None

    def edge_id_factory(self, target_node: InstanceId, edge_type: InstanceId) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )

class AssetCountByParent(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    parent: InstanceId | None = None

# Setup engine
engine = Engine.from_config_file(Path("cognite-sdk-config.yaml"))

# 1. Query with complex filters
statement = (
    select(CogniteAsset)
    .where(
        and_(
            col(CogniteAsset.aliases).contains_any_(["pump", "equipment"]),
            col(CogniteAsset.description).exists_(),
            or_(
                col(CogniteAsset.parent).nested_(col(CogniteAsset.name) == "Root Asset"),
                col(CogniteAsset.name).prefix("Pump-"),
            ),
        )
    )
    .asc(CogniteAsset.name)
    .limit(100)
)

results = engine.query(statement)
print(f"Found {len(results.data)} assets")

# 2. Search with filters
search_results = engine.search(
    search(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["pump"]))
    .query_by("industrial equipment", [CogniteAsset.name, CogniteAsset.description])
)

# 3. Aggregate
aggregate_results = engine.aggregate(
    aggregate(AssetCountByParent, "count")
    .where(col(CogniteAsset.description).exists_())
    .group_by(col(AssetCountByParent.parent))
)

for result in aggregate_results:
    print(f"Parent: {result.parent}, Count: {result.value}")

# 4. Update instances
assets = engine.query_all_pages(
    select(CogniteAsset).where(col(CogniteAsset.name).prefix("Pump-"))
)

for asset in assets:
    if "legacy" not in asset.aliases:
        asset.aliases.append("legacy")

engine.upsert(assets, replace=False)

# 5. Delete obsolete assets
obsolete = engine.search(
    search(CogniteAsset)
    .query_by("obsolete", [CogniteAsset.name])
)
engine.delete(obsolete)
```

---

## 🎯 Best Practices

1. **Models** — Declare only the fields you use; smaller models stay clearer and faster
2. **View Configuration**: Use `instance_spaces` or `instance_spaces_prefix` to optimize queries
3. **Pagination**: Use `query_all_pages()` for small datasets, `query()` with cursors for large datasets
4. **Validation**: Use `ignoreOnError` mode when dealing with potentially inconsistent data
5. **Edge Relationships**: Always implement `edge_id_factory` for writable models with relationships
6. **Async Operations**: Use async methods when making multiple concurrent queries
7. **Filtering**: Use specific filters to reduce query size and improve performance

---

## 📚 Additional Resources

- [Cognite Data Fusion Documentation](https://docs.cognite.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

See LICENSE file for details.
