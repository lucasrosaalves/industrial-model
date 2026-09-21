import logging
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
from cognite.client.data_classes.data_modeling.views import (
    MultiEdgeConnection,
    MultiReverseDirectRelation,
    SingleReverseDirectRelation,
)

import industrial_model
from industrial_model import ViewProperty, ViewSchema
from industrial_model.cognite_adapters.view_schema import render_view_schemas


def test_view_schema_is_exported_from_industrial_model() -> None:
    assert "ViewSchema" in industrial_model.__all__
    assert "ViewProperty" in industrial_model.__all__


def test_view_schema_accepts_property_constructors() -> None:
    schema = ViewSchema(
        space="cdf_cdm",
        external_id="CogniteAsset",
        version="v1",
        properties={
            "name": ViewProperty("mapped"),
            "aliases": ViewProperty("mapped", is_list=True),
        },
    )

    assert schema.properties["name"].kind == "mapped"
    assert schema.properties["aliases"].is_list is True
    assert "ViewProperty('mapped')" in schema.as_source()


def test_view_schema_from_cognite_keeps_only_runtime_fields() -> None:
    schema = ViewSchema.from_cognite(_asset_view())

    assert schema.space == "cdf_cdm"
    assert schema.external_id == "CogniteAsset"
    assert schema.version == "v1"
    assert schema.as_id() == ViewId("cdf_cdm", "CogniteAsset", "v1")
    assert schema.as_property_ref("name") == ("cdf_cdm", "CogniteAsset/v1", "name")

    name = schema.properties["name"]
    assert name.kind == "mapped"
    assert name.source is None
    assert name.is_list is False

    aliases = schema.properties["aliases"]
    assert aliases.kind == "mapped"
    assert aliases.is_list is True

    parent = schema.properties["parent"]
    assert parent.kind == "mapped"
    assert parent.source == ViewId("cdf_cdm", "CogniteAsset", "v1")

    files = schema.properties["files"]
    assert files.kind == "reverse"
    assert files.source == ViewId("cdf_cdm", "CogniteFile", "v1")
    assert files.through == "assets"
    assert files.is_list is True

    activity = schema.properties["activity"]
    assert activity.kind == "reverse"
    assert activity.source == ViewId("cdf_cdm", "CogniteActivity", "v1")
    assert activity.through == "asset"
    assert activity.is_list is False

    related = schema.properties["related"]
    assert related.kind == "edge"
    assert related.source == ViewId("cdf_cdm", "CogniteEquipment", "v1")
    assert related.direction == "outwards"
    assert related.edge_type == DirectRelationReference("cdf_cdm", "relatedTo")

    children = schema.properties["children"]
    assert children.kind == "edge"
    assert children.direction == "inwards"
    assert children.edge_type == DirectRelationReference("cdf_cdm", "parentOf")


def test_view_schema_source_uses_owned_constructors() -> None:
    schema = ViewSchema.from_cognite(_asset_view())
    rendered = schema.as_source()

    assert rendered == render_view_schemas([schema])[1:-1]
    assert (
        "source=ViewId(space='cdf_cdm', external_id='CogniteAsset', version='v1')"
        in rendered
    )
    assert (
        "edge_type=DirectRelationReference(space='cdf_cdm', external_id='relatedTo')"
        in rendered
    )
    assert "direction='inwards'" in rendered
    assert "through='asset'" in rendered
    assert "writable" not in rendered
    assert "usedFor" not in rendered
    assert "lastUpdatedTime" not in rendered
    assert "containerPropertyIdentifier" not in rendered
    assert len(rendered) < len(repr(_asset_view().dump()))


def test_from_cognite_warns_on_unsupported_property(
    caplog: pytest.LogCaptureFixture,
) -> None:
    view = _asset_view()
    view.properties["custom"] = object()  # type: ignore[assignment]

    with caplog.at_level(logging.WARNING):
        schema = ViewSchema.from_cognite(view)

    assert "custom" not in schema.properties
    assert "name" in schema.properties
    assert "Skipping unsupported property 'custom'" in caplog.text
    assert "CogniteAsset" in caplog.text
    assert "object" in caplog.text


def _asset_view() -> View:
    container = ContainerId("cdf_cdm", "CogniteAsset")
    view_id = ViewId("cdf_cdm", "CogniteAsset", "v1")
    file_view_id = ViewId("cdf_cdm", "CogniteFile", "v1")
    activity_view_id = ViewId("cdf_cdm", "CogniteActivity", "v1")
    equipment_view_id = ViewId("cdf_cdm", "CogniteEquipment", "v1")
    properties: dict[str, Any] = {
        "name": MappedProperty(
            container=container,
            container_property_identifier="name",
            type=Text(),
            nullable=False,
            immutable=False,
            auto_increment=False,
        ),
        "aliases": MappedProperty(
            container=container,
            container_property_identifier="aliases",
            type=Text(is_list=True),
            nullable=False,
            immutable=False,
            auto_increment=False,
        ),
        "parent": MappedProperty(
            container=container,
            container_property_identifier="parent",
            type=DirectRelation(),
            nullable=True,
            immutable=False,
            auto_increment=False,
            source=view_id,
        ),
        "files": MultiReverseDirectRelation(
            source=file_view_id,
            through=PropertyId(file_view_id, "assets"),
        ),
        "activity": SingleReverseDirectRelation(
            source=activity_view_id,
            through=PropertyId(activity_view_id, "asset"),
        ),
        "related": MultiEdgeConnection(
            type=DirectRelationReference("cdf_cdm", "relatedTo"),
            source=equipment_view_id,
            name="related",
            description=None,
            edge_source=None,
            direction="outwards",
        ),
        "children": MultiEdgeConnection(
            type=DirectRelationReference("cdf_cdm", "parentOf"),
            source=view_id,
            name="children",
            description=None,
            edge_source=None,
            direction="inwards",
        ),
    }
    return View(
        space="cdf_cdm",
        external_id="CogniteAsset",
        version="v1",
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
