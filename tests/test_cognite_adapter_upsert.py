import asyncio
from typing import Any

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

from industrial_model.cognite_adapters import CogniteAdapter
from industrial_model.cognite_adapters.view_mapper import ViewMapperCache
from industrial_model.config import DataModelId
from industrial_model.models import InstanceId, WritableViewInstance


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


class _FakeInstances:
    def __init__(self) -> None:
        self.apply_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    async def apply(self, **kwargs: Any) -> None:
        self.apply_calls.append(kwargs)

    async def delete(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)


class _FakeDataModeling:
    def __init__(self) -> None:
        self.instances = _FakeInstances()


class _FakeCogniteClient:
    def __init__(self) -> None:
        self.data_modeling = _FakeDataModeling()


def test_adapter_forwards_skip_on_version_conflict_to_node_and_edge_apply() -> None:
    client = _FakeCogniteClient()
    adapter = _adapter(client)

    asyncio.run(
        adapter.upsert(
            [_sample_asset()],
            skip_on_version_conflict=True,
            ingestion_mode="create",
        )
    )

    assert len(client.data_modeling.instances.apply_calls) == 2
    node_call, edge_call = client.data_modeling.instances.apply_calls
    assert node_call["skip_on_version_conflict"] is True
    assert edge_call["skip_on_version_conflict"] is True
    assert node_call["nodes"][0].existing_version == 0
    assert edge_call["edges"][0].existing_version is None


def test_adapter_defaults_skip_on_version_conflict_to_false() -> None:
    client = _FakeCogniteClient()
    adapter = _adapter(client)

    asyncio.run(adapter.upsert([_sample_asset()]))

    assert client.data_modeling.instances.apply_calls
    for call in client.data_modeling.instances.apply_calls:
        assert call["skip_on_version_conflict"] is False
        items = call.get("nodes") or call.get("edges")
        assert items
        assert items[0].existing_version is None


def _adapter(client: _FakeCogniteClient) -> CogniteAdapter:
    return CogniteAdapter(
        client,  # type: ignore[arg-type]
        DataModelId(space="test-space", external_id="model", version="v1"),
        ViewMapperCache([_asset_view()]),
    )


def _sample_asset() -> SampleAsset:
    return SampleAsset(
        external_id="asset-1",
        space="test-space",
        name="Asset",
        related=[InstanceId(external_id="target-1", space="test-space")],
    )


def _asset_view() -> View:
    return View(
        space="test-space",
        external_id=SampleAsset.get_view_external_id(),
        version="version",
        properties={
            "name": MappedProperty(
                container=ContainerId("test-space", "container"),
                container_property_identifier="name",
                type=Text(),
                nullable=True,
                immutable=False,
                auto_increment=False,
            ),
            "related": MultiEdgeConnection(
                type=DirectRelationReference("test-space", "relatedTo"),
                source=ViewId("test-space", "Target", "version"),
                name="related",
                description=None,
                edge_source=None,
                direction="outwards",
            ),
        },
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
