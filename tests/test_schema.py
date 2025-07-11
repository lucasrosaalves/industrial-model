from pydantic import BaseModel

from industrial_model.models import get_schema_properties
from tests.models import (
    CogniteDescribable,
)

SEP = "|"


class _Car(BaseModel):
    model: str
    year: int
    owner: "SuperNestedModel"
    previous_owners: list["SuperNestedModel"] | None


class SuperNestedModel(CogniteDescribable):
    parent: "SuperNestedModel"
    children: list["SuperNestedModel"]
    cars: list[_Car] | None


def test_get_schema_properties() -> None:
    for entity, expected_schema in _get_test_schema().items():
        schema = get_schema_properties(entity, SEP)

        assert sorted(schema) == sorted(
            expected_schema
        ), f"{entity.__name__}: Expected {expected_schema}"


def _get_test_schema() -> dict[type[BaseModel], list[str]]:
    return {
        CogniteDescribable: [
            "aliases",
            "description",
            "externalId",
            "name",
            "space",
            "tags",
        ],
        SuperNestedModel: [
            "aliases",
            "cars",
            "cars|model",
            "cars|owner",
            "cars|owner|aliases",
            "cars|owner|cars",
            "cars|owner|cars|model",
            "cars|owner|cars|owner",
            "cars|owner|cars|previous_owners",
            "cars|owner|cars|year",
            "cars|owner|children",
            "cars|owner|description",
            "cars|owner|externalId",
            "cars|owner|name",
            "cars|owner|parent",
            "cars|owner|parent|aliases",
            "cars|owner|parent|cars",
            "cars|owner|parent|cars|model",
            "cars|owner|parent|cars|owner",
            "cars|owner|parent|cars|previous_owners",
            "cars|owner|parent|cars|year",
            "cars|owner|parent|children",
            "cars|owner|parent|description",
            "cars|owner|parent|externalId",
            "cars|owner|parent|name",
            "cars|owner|parent|parent",
            "cars|owner|parent|parent|aliases",
            "cars|owner|parent|parent|cars",
            "cars|owner|parent|parent|cars|model",
            "cars|owner|parent|parent|cars|owner",
            "cars|owner|parent|parent|cars|previous_owners",
            "cars|owner|parent|parent|cars|year",
            "cars|owner|parent|parent|children",
            "cars|owner|parent|parent|description",
            "cars|owner|parent|parent|externalId",
            "cars|owner|parent|parent|name",
            "cars|owner|parent|parent|parent",
            "cars|owner|parent|parent|space",
            "cars|owner|parent|parent|tags",
            "cars|owner|parent|space",
            "cars|owner|parent|tags",
            "cars|owner|space",
            "cars|owner|tags",
            "cars|previous_owners",
            "cars|year",
            "children",
            "children|aliases",
            "children|cars",
            "children|cars|model",
            "children|cars|owner",
            "children|cars|previous_owners",
            "children|cars|year",
            "children|children",
            "children|description",
            "children|externalId",
            "children|name",
            "children|parent",
            "children|parent|aliases",
            "children|parent|cars",
            "children|parent|cars|model",
            "children|parent|cars|owner",
            "children|parent|cars|previous_owners",
            "children|parent|cars|year",
            "children|parent|children",
            "children|parent|description",
            "children|parent|externalId",
            "children|parent|name",
            "children|parent|parent",
            "children|parent|space",
            "children|parent|tags",
            "children|space",
            "children|tags",
            "description",
            "externalId",
            "name",
            "parent",
            "parent|aliases",
            "parent|cars",
            "parent|cars|model",
            "parent|cars|owner",
            "parent|cars|previous_owners",
            "parent|cars|year",
            "parent|children",
            "parent|description",
            "parent|externalId",
            "parent|name",
            "parent|parent",
            "parent|parent|aliases",
            "parent|parent|cars",
            "parent|parent|cars|model",
            "parent|parent|cars|owner",
            "parent|parent|cars|previous_owners",
            "parent|parent|cars|year",
            "parent|parent|children",
            "parent|parent|description",
            "parent|parent|externalId",
            "parent|parent|name",
            "parent|parent|parent",
            "parent|parent|space",
            "parent|parent|tags",
            "parent|space",
            "parent|tags",
            "space",
            "tags",
        ],
    }
