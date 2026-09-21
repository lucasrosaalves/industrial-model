import asyncio
from typing import Any, cast

from industrial_model import (
    AggregatedViewInstance,
    Engine,
    InstanceId,
    WritableViewInstance,
)
from industrial_model.models import IngestionMode
from industrial_model.view_client import ViewClient


class _Asset(WritableViewInstance):
    name: str | None = None

    def edge_id_factory(
        self, target_node: InstanceId, edge_type: InstanceId
    ) -> InstanceId:
        return InstanceId(
            external_id=(
                f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}"
            ),
            space=self.space,
        )


class _AssetAggregation(AggregatedViewInstance):
    pass


class _RecordingEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upsert(
        self,
        entries: list[_Asset],
        replace: bool = False,
        remove_unset: bool = False,
        skip_on_version_conflict: bool = False,
        ingestion_mode: IngestionMode = "upsert",
    ) -> None:
        self.calls.append(
            {
                "entries": entries,
                "replace": replace,
                "remove_unset": remove_unset,
                "skip_on_version_conflict": skip_on_version_conflict,
                "ingestion_mode": ingestion_mode,
            }
        )

    async def upsert_async(
        self,
        entries: list[_Asset],
        replace: bool = False,
        remove_unset: bool = False,
        skip_on_version_conflict: bool = False,
        ingestion_mode: IngestionMode = "upsert",
    ) -> None:
        self.upsert(
            entries,
            replace,
            remove_unset,
            skip_on_version_conflict,
            ingestion_mode,
        )


def _client(engine: _RecordingEngine) -> ViewClient[Any, Any, Any, Any, Any, Any, Any]:
    return ViewClient(cast(Engine, engine), _Asset, _AssetAggregation)


def test_view_client_upsert_forwards_remove_unset() -> None:
    engine = _RecordingEngine()
    asset = _Asset(external_id="asset-1", space="space", name="Pump")

    _client(engine).upsert(
        [asset],
        replace=False,
        remove_unset=True,
        skip_on_version_conflict=True,
        ingestion_mode="create",
    )

    assert engine.calls == [
        {
            "entries": [asset],
            "replace": False,
            "remove_unset": True,
            "skip_on_version_conflict": True,
            "ingestion_mode": "create",
        }
    ]


def test_view_client_upsert_async_forwards_remove_unset() -> None:
    engine = _RecordingEngine()
    asset = _Asset(external_id="asset-1", space="space", name="Pump")

    asyncio.run(
        _client(engine).upsert_async(
            [asset],
            remove_unset=True,
        )
    )

    assert engine.calls == [
        {
            "entries": [asset],
            "replace": False,
            "remove_unset": True,
            "skip_on_version_conflict": False,
            "ingestion_mode": "upsert",
        }
    ]
