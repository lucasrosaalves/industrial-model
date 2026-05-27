from typing import Any

from cognite.client.data_classes.data_modeling import (
    ContainerId,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.data_types import DirectRelation, Text
from cognite.client.data_classes.data_modeling.query import Select

from industrial_model.cognite_adapters.query_mapper import QueryMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapper
from industrial_model.constants import NESTED_SEP
from industrial_model.models import InstanceId, ViewInstance
from industrial_model.statements import select


class ParentType(ViewInstance):
    code: str


class ParentModel(ViewInstance):
    name: str
    type: InstanceId | ParentType | None = None


class AssetWithRelations(ViewInstance):
    parent: InstanceId | ParentModel | None = None
    asset_type: InstanceId | ParentType | None = None


class FakeViewMapper(ViewMapper):
    def __init__(self, views: dict[str, View]) -> None:
        self._views = views

    def get_view(self, view_external_id: str) -> View:
        return self._views[view_external_id]


def test_query_mapper_uses_instance_id_relation_mode_to_skip_dependency_query() -> None:
    mapper = QueryMapper(_fake_view_mapper())

    query = mapper.map(
        select(AssetWithRelations).relation_mode(
            AssetWithRelations.parent, "instanceId"
        )
    )

    root = AssetWithRelations.get_view_external_id()
    assert f"{root}{NESTED_SEP}parent" not in query.with_
    assert f"{root}{NESTED_SEP}assetType" in query.with_
    assert _select_properties(query.select[root]) == ["parent", "assetType"]
    assert _select_properties(query.select[f"{root}{NESTED_SEP}assetType"]) == ["code"]


def test_query_mapper_keeps_nested_instance_id_reference_without_child_query() -> None:
    mapper = QueryMapper(_fake_view_mapper())

    query = mapper.map(
        select(AssetWithRelations).relation_mode(
            f"parent{NESTED_SEP}type", "instanceId"
        )
    )

    root = AssetWithRelations.get_view_external_id()
    parent_key = f"{root}{NESTED_SEP}parent"
    parent_type_key = f"{parent_key}{NESTED_SEP}type"

    assert parent_key in query.with_
    assert parent_type_key not in query.with_
    assert _select_properties(query.select[parent_key]) == ["name", "type"]


def _fake_view_mapper() -> FakeViewMapper:
    parent_id = _view_id(ParentModel)
    parent_type_id = _view_id(ParentType)

    return FakeViewMapper(
        {
            AssetWithRelations.get_view_external_id(): _view(
                AssetWithRelations,
                {
                    "parent": _mapped_property(
                        "parent", DirectRelation(), source=parent_id
                    ),
                    "assetType": _mapped_property(
                        "assetType", DirectRelation(), source=parent_type_id
                    ),
                },
            ),
            ParentModel.get_view_external_id(): _view(
                ParentModel,
                {
                    "name": _mapped_property("name", Text()),
                    "type": _mapped_property(
                        "type", DirectRelation(), source=parent_type_id
                    ),
                },
            ),
            ParentType.get_view_external_id(): _view(
                ParentType,
                {
                    "code": _mapped_property("code", Text()),
                },
            ),
        }
    )


def _view_id(model: type[ViewInstance]) -> ViewId:
    return ViewId("space", model.get_view_external_id(), "version")


def _view(model: type[ViewInstance], properties: dict[str, Any]) -> View:
    return View(
        space="space",
        external_id=model.get_view_external_id(),
        version="version",
        properties=properties,
        last_updated_time=0,
        created_time=0,
        description=None,
        name=None,
        filter=None,
        implements=None,
        writable=True,
        used_for="node",
        is_global=False,
    )


def _mapped_property(
    identifier: str,
    type_: Text | DirectRelation,
    source: ViewId | None = None,
) -> MappedProperty:
    return MappedProperty(
        container=ContainerId("space", "container"),
        container_property_identifier=identifier,
        type=type_,
        nullable=True,
        immutable=False,
        auto_increment=False,
        source=source,
    )


def _select_properties(select_: Select) -> list[str]:
    assert len(select_.sources) == 1
    properties = select_.sources[0].properties
    assert properties is not None
    return properties
