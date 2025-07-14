# 📦 industrial-model

`industrial-model` is a Python ORM-style abstraction for querying views in Cognite Data Fusion (CDF). It provides a declarative and type-safe way to model CDF views using `pydantic`, build queries, and interact with the CDF API in a Pythonic fashion.

---

## ✨ Features

- Define CDF views using Pydantic-style classes.
- Build complex queries using fluent and composable filters.
- Easily fetch data using standard or paginated query execution.
- Automatic alias and field transformation support.

---

## 📦 Installation

```bash
pip install industrial-model
```

---

# Usage Example

This section shows how to interact with **Cognite Data Fusion (CDF)** using the `industrial_model` package.  
We use the simplified version of the `CogniteAsset`view in the `CogniteCore` data model (version `v1`) as a sample for all the examples below.

---

```graphql
type CogniteAsset {
  name: String
  description: String
  tags: [String]
  parent: CogniteAsset
  root: CogniteAsset
}
```

---

## 🚀 Getting Started

### 1. Define Your Model (You only need to add the properties that you want to retrieve)

```python
from industrial_model import ViewInstance

class CogniteAsset(ViewInstance):
    name: str
    description: str
    aliases: list[str]
```

### 2. Create the Engine

#### Option A: From Configuration File

Create a `cognite-sdk-config.yaml` file with your credentials and model configuration:

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

#### Option B: Manually

```python
from cognite.client import CogniteClient
from industrial_model import Engine, DataModelId

engine = Engine(
    cognite_client=CogniteClient(), # you need to create a valid cognite client
    data_model_id=DataModelId(external_id="CogniteCore", space="cdf_cdm", version="v1")
)
```

---

## 🔎 Querying Assets by Alias

```python
from industrial_model import select, col

statement = (
    select(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
    .limit(1000)
)

results = engine.query_all_pages(statement)
```

---

## 🔗 Filtering by Parent Name

```python
class CogniteAsset(ViewInstance):
    name: str
    description: str
    aliases: list[str]
    parent: CogniteAsset | None = None
```

```python
statement = (
    select(CogniteAsset)
    .where(
        col(CogniteAsset.aliases).contains_any_(["my_alias"]) &
        col(CogniteAsset.parent).nested_(col(CogniteAsset.name) == "Parent Asset Name")
    )
)

results = engine.query(statement)
```

---

## 🔗 Filtering by Parent Name with bool operators

```python
from industrial_model import select, col, or_, and_

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

results = engine.query(statement)
```

---

## 🔗 Paginating with cursor and sort by name

```python
class CogniteAsset(ViewInstance):
    name: str
    description: str
    aliases: list[str]
    parent: CogniteAsset | None = None
```

```python
statement = select(CogniteAsset).asc(CogniteAsset.name).cursor("NEXT_CURSOR")

results = engine.query(statement)
```

---

## 🔗 Proving an alias for a property

```python
from pydantic import Field

class CogniteAsset(ViewInstance):
    another_name: str = Field(alias="name")
```

---

## 🎯 Optimize Query with View Config - The spaces will be appended in every query

```python
from industrial_model import ViewInstanceConfig

class CogniteAsset(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="CogniteAsset",  # Maps this class to the 'CogniteAsset' view
        instance_spaces_prefix="Industr-",  # Filters queries to spaces with this prefix
        instance_spaces=[
            "Industrial-Data"
        ],  # Alternatively, explicitly filter by these spaces
    )
    name: str
    description: str
    aliases: list[str]
    parent: CogniteAsset | None = None
```

---

## 🔍 Search by Fuzzy Name

```python
from industrial_model import search

search_statement = (
    search(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
    .query_by("my fuzzy name", [CogniteAsset.name])
)

search_result = engine.search(search_statement)
```

---

## 📊 Aggregating Data

```python
from industrial_model import aggregate, AggregatedViewInstance

class CogniteAssetByName(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str

aggregate_statement = aggregate(CogniteAssetByName, "count").group_by(
    col(CogniteAssetByName.name)
)

aggregate_result = engine.aggregate(aggregate_statement)
```

---

## 🗑️ Deleting Instances

```python
instances_to_delete = engine.search(
    search(CogniteAsset)
    .where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
    .query_by("my fuzzy name", [CogniteAsset.name])
)

engine.delete(instances_to_delete)
```

---

## ✏️ Upserting Instances

```python
from industrial_model import WritableViewInstance, InstanceId

class CogniteAsset(WritableViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str
    aliases: list[str]

    def edge_id_factory(self, target_node: InstanceId, edge_type: InstanceId) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )
```

```python
instances = engine.query_all_pages(
    select(CogniteAsset).where(col(CogniteAsset.aliases).contains_any_(["my_alias"]))
)

for instance in instances:
    instance.aliases.append("new_alias")

engine.upsert(instances, replace=False)
```

---

## ✏️ Async version

All methods have a async equivalent version

```python
await engine.query_async(...)
await engine.query_all_pages_async(...)
await engine.search_async(...)
await engine.aggregate_async(...)
await engine.delete_async(...)
await engine.upsert_async(...)
```

---
