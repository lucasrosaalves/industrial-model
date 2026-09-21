from typing import Any

import pytest
from cognite.client.data_classes.data_modeling import (
    ContainerId,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.data_types import (
    DirectRelationReference,
    Text,
)
from cognite.client.data_classes.data_modeling.views import MultiEdgeConnection

from industrial_model import ViewProperty, ViewSchema
from industrial_model.cognite_adapters.upsert_mapper import UpsertMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapperCache
from industrial_model.models import InstanceId, ViewInstance, WritableViewInstance


class SampleAsset(WritableViewInstance):
    name: str
    related: list[InstanceId] = []

    def edge_id_factory(
        self, target_node: InstanceId, edge_type: InstanceId
    ) -> InstanceId:
        return InstanceId(
            external_id=(
                f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}"
            ),
            space=self.space,
        )


def test_upsert_mode_omits_existing_version_on_nodes() -> None:
    mapper = UpsertMapper(_fake_view_mapper())
    operation = mapper.map([_sample_asset()], remove_unset=False)

    assert len(operation.nodes) == 1
    assert operation.nodes[0].existing_version is None
    assert "existingVersion" not in operation.nodes[0].dump()
    assert len(operation.edges) == 1
    assert operation.edges[0].existing_version is None


def test_create_mode_sets_existing_version_zero_on_nodes_only() -> None:
    mapper = UpsertMapper(_fake_view_mapper())
    operation = mapper.map(
        [_sample_asset()],
        remove_unset=False,
        ingestion_mode="create",
    )

    assert operation.nodes[0].existing_version == 0
    assert operation.nodes[0].dump()["existingVersion"] == 0
    assert operation.edges[0].existing_version is None
    assert "existingVersion" not in operation.edges[0].dump()


def test_upsert_raises_when_edge_type_is_missing() -> None:
    mapper = UpsertMapper(
        ViewMapperCache(
            [
                ViewSchema(
                    space="test-space",
                    external_id=SampleAsset.get_view_external_id(),
                    version="version",
                    properties={
                        "name": ViewProperty("mapped"),
                        "related": ViewProperty("edge"),
                    },
                )
            ]
        )
    )

    with pytest.raises(ValueError, match="related is missing a type"):
        mapper.map([_sample_asset()], remove_unset=False)


def _sample_asset() -> SampleAsset:
    return SampleAsset(
        external_id="asset-1",
        space="test-space",
        name="Asset",
        related=[InstanceId(external_id="target-1", space="test-space")],
    )


def _fake_view_mapper() -> ViewMapperCache:
    return ViewMapperCache(
        [
            ViewSchema.from_cognite(
                _view(
                    SampleAsset,
                    {
                        "name": _mapped_property("name", Text()),
                        "related": MultiEdgeConnection(
                            type=DirectRelationReference("test-space", "relatedTo"),
                            source=ViewId("test-space", "Target", "version"),
                            name="related",
                            description=None,
                            edge_source=None,
                            direction="outwards",
                        ),
                    },
                )
            )
        ]
    )


def _view(model: type[ViewInstance], properties: dict[str, Any]) -> View:
    return View(
        space="test-space",
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


def _mapped_property(identifier: str, type_: Text) -> MappedProperty:
    return MappedProperty(
        container=ContainerId("test-space", "container"),
        container_property_identifier=identifier,
        type=type_,
        nullable=True,
        immutable=False,
        auto_increment=False,
    )
