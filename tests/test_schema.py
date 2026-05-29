from pydantic import BaseModel

from industrial_model.models import (
    InstanceId,
    ViewInstance,
    get_schema_properties,
)
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


class TimeSeries(CogniteDescribable):
    name: str | None


class CogniteAsset(CogniteDescribable):
    parent: "CogniteAsset | None"

    timeseries: InstanceId | TimeSeries | None

    my_list: list[InstanceId | TimeSeries] | None = None


class ParentType(ViewInstance):
    code: str


class ParentModel(ViewInstance):
    name: str
    type: InstanceId | ParentType | None = None


class AssetWithUnionParent(ViewInstance):
    parent: InstanceId | ParentModel | None = None
    asset_type: InstanceId | ParentType | None = None


class ScalarSharedRelation(ViewInstance):
    shared: str


class NestedSharedRelation(ViewInstance):
    shared: ParentType


class AssetWithOverlappingUnion(ViewInstance):
    relation: NestedSharedRelation | ScalarSharedRelation | None = None


class MutualA(ViewInstance):
    b: "MutualB | None" = None


class MutualB(ViewInstance):
    a: MutualA | None = None


def test_get_schema_properties() -> None:
    for entity, expected_schema in _get_test_schema().items():
        schema = get_schema_properties(entity, SEP)

        assert sorted(schema) == sorted(expected_schema), (
            f"{entity.__name__}: Expected {expected_schema}"
        )


def test_build_relation_projection_instance_id_mode() -> None:
    schema = get_schema_properties(
        AssetWithUnionParent,
        SEP,
        "AssetWithUnionParent",
        {"parent": "instanceId"},
    )

    expected_schema = [
        "AssetWithUnionParent|externalId",
        "AssetWithUnionParent|space",
        "AssetWithUnionParent|parent",
        "AssetWithUnionParent|parent|externalId",
        "AssetWithUnionParent|parent|space",
        "AssetWithUnionParent|assetType",
        "AssetWithUnionParent|assetType|externalId",
        "AssetWithUnionParent|assetType|space",
        "AssetWithUnionParent|assetType|code",
    ]

    assert sorted(schema) == sorted(expected_schema)


def test_build_relation_projection_model_mode_prefers_view_model_union() -> None:
    schema = get_schema_properties(
        AssetWithUnionParent,
        SEP,
        "AssetWithUnionParent",
        {"parent": "model"},
    )

    assert "AssetWithUnionParent|parent" in schema
    assert "AssetWithUnionParent|parent|name" in schema


def test_build_relation_projection_includes_ancestors() -> None:
    schema = get_schema_properties(
        AssetWithUnionParent,
        SEP,
        "AssetWithUnionParent",
        {f"parent{SEP}type": "instanceId"},
    )

    assert "AssetWithUnionParent|parent" in schema
    assert "AssetWithUnionParent|parent|type" in schema
    assert "AssetWithUnionParent|parent|type|externalId" in schema
    assert "AssetWithUnionParent|parent|type|space" in schema
    assert "AssetWithUnionParent|parent|type|code" not in schema


def test_build_relation_projection_omits_unspecified_relations() -> None:
    schema = get_schema_properties(
        AssetWithUnionParent,
        SEP,
        "AssetWithUnionParent",
        {"parent": "instanceId"},
    )
    assert "AssetWithUnionParent|parent|name" not in schema
    assert "AssetWithUnionParent|assetType" in schema
    assert "AssetWithUnionParent|assetType|code" in schema


def test_schema_properties_preserve_nested_paths_in_overlapping_unions() -> None:
    schema = get_schema_properties(AssetWithOverlappingUnion, SEP)

    assert "relation|shared" in schema
    assert "relation|shared|code" in schema


def test_schema_properties_stop_mutual_reference_cycles() -> None:
    schema = get_schema_properties(MutualA, SEP)

    assert "b|a|b|a" in schema
    assert "b|a|b|a|b" not in schema


def test_schema_properties_for_asset_timeseries_merges_instance_id_and_model() -> None:
    schema = get_schema_properties(CogniteAsset, SEP)

    # InstanceId properties surfaced via the union
    assert "timeseries|externalId" in schema
    assert "timeseries|space" in schema
    # TimeSeries model properties surfaced via the union
    assert "timeseries|name" in schema
    assert "timeseries|description" in schema


def test_schema_properties_for_asset_list_union_expands_element_type() -> None:
    schema = get_schema_properties(CogniteAsset, SEP)

    assert "myList" in schema
    assert "myList|externalId" in schema
    assert "myList|name" in schema


def test_schema_properties_for_asset_self_reference_stops_at_shallow_props() -> None:
    schema = get_schema_properties(CogniteAsset, SEP)

    assert "parent|parent|parent" in schema
    # Cycle detected — third-level parent expands only shallow (no further nesting)
    assert "parent|parent|parent|parent" not in schema
    assert "parent|parent|parent|name" not in schema


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
        CogniteAsset: [
            "aliases",
            "description",
            "externalId",
            "myList",
            "myList|aliases",
            "myList|description",
            "myList|externalId",
            "myList|name",
            "myList|space",
            "myList|tags",
            "name",
            "parent",
            "parent|aliases",
            "parent|description",
            "parent|externalId",
            "parent|myList",
            "parent|myList|aliases",
            "parent|myList|description",
            "parent|myList|externalId",
            "parent|myList|name",
            "parent|myList|space",
            "parent|myList|tags",
            "parent|name",
            "parent|parent",
            "parent|parent|aliases",
            "parent|parent|description",
            "parent|parent|externalId",
            "parent|parent|myList",
            "parent|parent|myList|aliases",
            "parent|parent|myList|description",
            "parent|parent|myList|externalId",
            "parent|parent|myList|name",
            "parent|parent|myList|space",
            "parent|parent|myList|tags",
            "parent|parent|name",
            "parent|parent|parent",
            "parent|parent|space",
            "parent|parent|tags",
            "parent|parent|timeseries",
            "parent|parent|timeseries|aliases",
            "parent|parent|timeseries|description",
            "parent|parent|timeseries|externalId",
            "parent|parent|timeseries|name",
            "parent|parent|timeseries|space",
            "parent|parent|timeseries|tags",
            "parent|space",
            "parent|tags",
            "parent|timeseries",
            "parent|timeseries|aliases",
            "parent|timeseries|description",
            "parent|timeseries|externalId",
            "parent|timeseries|name",
            "parent|timeseries|space",
            "parent|timeseries|tags",
            "space",
            "tags",
            "timeseries",
            "timeseries|aliases",
            "timeseries|description",
            "timeseries|externalId",
            "timeseries|name",
            "timeseries|space",
            "timeseries|tags",
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
