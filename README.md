# 📦 industrial-model

`industrial-model` is a Python ORM-style abstraction for querying views and data models in Cognite Data Fusion (CDF). It provides a declarative and type-safe way to model CDF views using `pydantic`, build queries, and interact with the CDF API in a Pythonic fashion.

---

## ✨ Features

- Define CDF views using Pydantic-style classes.
- Build complex queries using fluent and composable filters.
- Easily fetch data using standard or paginated query execution.
- Automatic alias and field transformation support.
- Extensible and test-friendly design.

---

## 📦 Installation

```bash
pip install industrial-model
```

---

## 🛠️ Usage Example

```python
import datetime
from cognite.client import CogniteClient
from pydantic import Field

from industrial_model import (
    aggregate,
    AggregatedViewInstance,
    AsyncEngine,
    DataModelId,
    Engine,
    InstanceId,
    ViewInstance,
    ViewInstanceConfig,
    WritableViewInstance,
    and_,
    col,
    or_,
    select,
    search,
)

# Define entities (view instances)


class Car(ViewInstance):
    name: str


class Region(ViewInstance):
    name: str


class Country(ViewInstance):
    name: str
    region: Region = Field(
        alias="regionRef"
    )  # Maps property to field if names differ


class Person(ViewInstance):
    name: str
    birthday: datetime.date
    lives_in: Country
    cars: list[Car]


# By default, the ORM maps the class name to the view in the data model.
# You can override this behavior using the `view_config` field.

# For improved query performance, you can configure `instance_spaces` or `instance_spaces_prefix`
# in the `view_config`. These options include space filters in the generated queries,
# which can significantly reduce response times when working with large datasets.

class AnotherPerson(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="Person",                    # Maps this class to the 'Person' view
        instance_spaces_prefix="Industr-",            # Filters queries to spaces with this prefix
        instance_spaces=["Industrial-Data"]           # Alternatively, explicitly filter by these spaces
    )

    name: str
    birthday: datetime.date
    lives_in: Country
    cars: list[Car]


# Initialize Cognite client and data model engine

cognite_client = CogniteClient()

data_model_id = DataModelId(
    external_id="IndustrialData",
    space="IndustralSpaceType",
    version="v1"
)

engine = Engine(cognite_client, data_model_id)
async_engine = AsyncEngine(cognite_client, data_model_id)  # Optional async engine


# -----------------------------------
# Example Queries
# -----------------------------------

# 1. Basic query: Find person named "Lucas"
statement = select(Person).where(Person.name == "Lucas").limit(1)
result = engine.query(statement)


# 2. Combined filter with AND/OR
statement = select(Person).where(
    (Person.name == "Lucas") & (Person.birthday > datetime.date(2023, 1, 2)) |
    (Person.name == "Another")
)
result = engine.query(statement)


# 3. Same logic using `col()` expressions
statement = select(Person).where(
    (col("name").equals_("Lucas")) &
    (col(Person.birthday).gt_("2023-01-02")) |
    (Person.name == "Another")
)
result = engine.query(statement)


# 4. Nested filtering using relationships
statement = select(Person).where(
    or_(
        col(Person.lives_in).nested_(Country.name == "usa"),
        and_(
            col(Person.lives_in).nested_(col(Country.name).equals_("bra")),
            col(Person.birthday).equals_("2023-01-01")
        )
    )
)
result = engine.query(statement)


# 5. Paginated query with sorting and cursor
statement = (
    select(Person)
    .where(
        (Person.name == "Lucas") &
        (Person.birthday > datetime.date(2023, 1, 2)) |
        (Person.name == "Another")
    )
    .limit(10)
    .cursor("NEXT CURSOR")
    .asc(Person.name)
)
result = engine.query(statement)


# 6. Fetch all pages of a query
statement = select(Person).where(
    (Person.name == "Lucas") &
    (Person.birthday > datetime.date(2023, 1, 2)) |
    (Person.name == "Another")
)
all_results = engine.query_all_pages(statement)


# 7. Data Ingestion

class WritablePerson(WritableViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="Person"                    # Maps this class to the 'Person' view
    )
    name: str
    lives_in: InstanceId
    cars: list[InstanceId]

    # You need to implement the end_id_factory so the model can build the edge ids automatically.
    def edge_id_factory(
        self, target_node: InstanceId, edge_type: InstanceId
    ) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )

statement = select(WritablePerson).where(WritablePerson.external_id == "Lucas")
person = engine.query_all_pages(statement)[0]

person.lives_in = InstanceId(external_id="br", space="data-space")
person.cars.clear() # Gonna remove all car edges from the person

engine.upsert([person])



# 8. Aggregate

class AggregateByNamePerson(AggregatedViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="Person"  # Maps this class to the 'Person' view
    )

    name: str  # group by name


aggregate_result = engine.aggregate(aggregate(AggregateByNamePerson, "count"))



# 9. Deletion

class Entity(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="Person"
    )
    name: str


statement = select(Entity).where(Entity.external_id == "Lucas")
person = engine.query_all_pages(statement)[0]


engine.delete([person])


# 10. Search

#  Notes:
#     External ID searches work as prefix searches.
#     This method does not include edges or direct relations in the result model.
#     Filter does not support nested properties.

class Entity(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="Person"
    )
    name: str


statement = search(Entity).query_by("Lucas", [Entity.name])
person = engine.search(statement)


```

---
