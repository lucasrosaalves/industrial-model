from typing import Any

import pytest
from cognite.client.data_classes.data_modeling import (
    ContainerId,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.data_types import (
    DirectRelation,
    DirectRelationReference,
    Text,
)
from cognite.client.data_classes.data_modeling.ids import PropertyId
from cognite.client.data_classes.data_modeling.query import (
    EdgeResultSetExpression,
    NodeResultSetExpression,
    Select,
)
from cognite.client.data_classes.data_modeling.views import (
    MultiEdgeConnection,
    MultiReverseDirectRelation,
)

from industrial_model import ViewProperty, ViewSchema
from industrial_model.cognite_adapters.query_mapper import QueryMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapperCache
from industrial_model.constants import EDGE_MARKER, NESTED_SEP
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


class FileModel(ViewInstance):
    name: str


class EquipmentModel(ViewInstance):
    name: str


class AssetWithConnections(ViewInstance):
    files: list[FileModel] | None = None
    related: list[EquipmentModel] | None = None
    children: list["AssetWithConnections"] | None = None


def test_query_mapper_includes_reverse_relation() -> None:
    mapper = QueryMapper(_connections_view_mapper())

    query = mapper.map(select(AssetWithConnections))

    root = AssetWithConnections.get_view_external_id()
    files_key = f"{root}{NESTED_SEP}files"
    assert files_key in query.with_
    expression = query.with_[files_key]
    assert isinstance(expression, NodeResultSetExpression)
    assert expression.direction == "inwards"
    assert expression.through == PropertyId(
        source=ViewId("space", "FileModel", "version"),
        property="assets",
    )
    assert _select_properties(query.select[files_key]) == ["name", "assets"]


def test_query_mapper_includes_outwards_and_inwards_edges() -> None:
    mapper = QueryMapper(_connections_view_mapper())

    query = mapper.map(select(AssetWithConnections))

    root = AssetWithConnections.get_view_external_id()
    related_key = f"{root}{NESTED_SEP}related"
    related_edge_key = f"{related_key}{NESTED_SEP}{EDGE_MARKER}"
    children_key = f"{root}{NESTED_SEP}children"
    children_edge_key = f"{children_key}{NESTED_SEP}{EDGE_MARKER}"

    related_edge = query.with_[related_edge_key]
    children_edge = query.with_[children_edge_key]
    assert isinstance(related_edge, EdgeResultSetExpression)
    assert isinstance(children_edge, EdgeResultSetExpression)
    assert related_edge.direction == "outwards"
    assert children_edge.direction == "inwards"
    assert related_edge.filter is not None
    assert children_edge.filter is not None
    assert related_edge.filter.dump() == {
        "equals": {
            "property": ["edge", "type"],
            "value": {"space": "space", "externalId": "relatedTo"},
        }
    }
    assert children_edge.filter.dump() == {
        "equals": {
            "property": ["edge", "type"],
            "value": {"space": "space", "externalId": "parentOf"},
        }
    }
    related_node = query.with_[related_key]
    assert isinstance(related_node, NodeResultSetExpression)
    assert related_node.from_ == related_edge_key
    assert _select_properties(query.select[related_key]) == ["name"]


def test_query_mapper_raises_for_reverse_missing_through() -> None:
    mapper = QueryMapper(
        ViewMapperCache(
            [
                ViewSchema(
                    space="space",
                    external_id=AssetWithConnections.get_view_external_id(),
                    version="version",
                    properties={
                        "files": ViewProperty(
                            "reverse",
                            source=ViewId("space", "FileModel", "version"),
                        )
                    },
                ),
                ViewSchema(
                    space="space",
                    external_id="FileModel",
                    version="version",
                    properties={"name": ViewProperty("mapped")},
                ),
            ]
        )
    )

    with pytest.raises(ValueError, match="files is missing a source or through"):
        mapper.map(select(AssetWithConnections))


def test_query_mapper_raises_for_edge_missing_type() -> None:
    mapper = QueryMapper(
        ViewMapperCache(
            [
                ViewSchema(
                    space="space",
                    external_id=AssetWithConnections.get_view_external_id(),
                    version="version",
                    properties={
                        "related": ViewProperty(
                            "edge",
                            source=ViewId("space", "EquipmentModel", "version"),
                        )
                    },
                ),
                ViewSchema(
                    space="space",
                    external_id="EquipmentModel",
                    version="version",
                    properties={"name": ViewProperty("mapped")},
                ),
            ]
        )
    )

    with pytest.raises(ValueError, match="related is missing a source or type"):
        mapper.map(select(AssetWithConnections))


def _connections_view_mapper() -> ViewMapperCache:
    file_id = _view_id(FileModel)
    equipment_id = _view_id(EquipmentModel)
    asset_id = _view_id(AssetWithConnections)
    return ViewMapperCache(
        [
            ViewSchema.from_cognite(
                _view(
                    AssetWithConnections,
                    {
                        "files": MultiReverseDirectRelation(
                            source=file_id,
                            through=PropertyId(file_id, "assets"),
                        ),
                        "related": MultiEdgeConnection(
                            type=DirectRelationReference("space", "relatedTo"),
                            source=equipment_id,
                            name="related",
                            description=None,
                            edge_source=None,
                            direction="outwards",
                        ),
                        "children": MultiEdgeConnection(
                            type=DirectRelationReference("space", "parentOf"),
                            source=asset_id,
                            name="children",
                            description=None,
                            edge_source=None,
                            direction="inwards",
                        ),
                    },
                )
            ),
            ViewSchema.from_cognite(
                _view(
                    FileModel,
                    {
                        "name": _mapped_property("name", Text()),
                        "assets": _mapped_property(
                            "assets", DirectRelation(), source=asset_id
                        ),
                    },
                )
            ),
            ViewSchema.from_cognite(
                _view(
                    EquipmentModel,
                    {"name": _mapped_property("name", Text())},
                )
            ),
        ]
    )


def _fake_view_mapper() -> ViewMapperCache:
    parent_id = _view_id(ParentModel)
    parent_type_id = _view_id(ParentType)

    return ViewMapperCache(
        [
            ViewSchema.from_cognite(
                _view(
                    AssetWithRelations,
                    {
                        "parent": _mapped_property(
                            "parent", DirectRelation(), source=parent_id
                        ),
                        "assetType": _mapped_property(
                            "assetType", DirectRelation(), source=parent_type_id
                        ),
                    },
                )
            ),
            ViewSchema.from_cognite(
                _view(
                    ParentModel,
                    {
                        "name": _mapped_property("name", Text()),
                        "type": _mapped_property(
                            "type", DirectRelation(), source=parent_type_id
                        ),
                    },
                )
            ),
            ViewSchema.from_cognite(
                _view(
                    ParentType,
                    {
                        "code": _mapped_property("code", Text()),
                    },
                )
            ),
        ]
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
