import asyncio

import pytest
from cognite.client.config import global_config
from cognite.client.data_classes.data_modeling import ContainerId, MappedProperty, View
from cognite.client.data_classes.data_modeling.data_types import Text

from industrial_model import AsyncEngine, Engine, ViewMapperCache
from industrial_model.cognite_adapters.view_mapper import ViewMapper

from .test_engine_setup import DATA_MODEL_ID


def test_view_mapper_cache_returns_preloaded_views() -> None:
    cache = ViewMapperCache(
        [_name_view("CogniteAsset"), _name_view("CogniteEquipment")]
    )

    assert cache.get_view("CogniteAsset").external_id == "CogniteAsset"
    assert cache.get_view("CogniteEquipment").version == "v1"


def test_view_mapper_cache_raises_for_unknown_view() -> None:
    cache = ViewMapperCache([_name_view("CogniteAsset")])

    with pytest.raises(ValueError, match="CogniteEquipment is not available"):
        cache.get_view("CogniteEquipment")


def test_view_mapper_cache_load_views_is_noop() -> None:
    cache = ViewMapperCache([_name_view("CogniteAsset")])

    asyncio.run(cache.load_views())

    assert cache.get_view("CogniteAsset").external_id == "CogniteAsset"


def test_view_mapper_cache_roundtrips_dumps() -> None:
    view = _name_view("CogniteAsset")
    cache = ViewMapperCache.from_dumps([view.dump()])

    loaded = cache.get_view("CogniteAsset")
    assert loaded.external_id == "CogniteAsset"
    assert "name" in loaded.properties


def test_engine_uses_view_mapper_cache() -> None:
    global_config.disable_pypi_version_check = True
    cache = ViewMapperCache([_name_view("CogniteAsset")])
    engine = Engine.from_user_token(
        user_token="user-token",
        project="project",
        cluster="api",
        data_model_id=DATA_MODEL_ID,
        view_mapper_cache=cache,
    )

    assert engine._cognite_adapter._view_mapper is cache
    assert isinstance(engine._cognite_adapter._view_mapper, ViewMapper)


def test_async_engine_uses_view_mapper_cache() -> None:
    global_config.disable_pypi_version_check = True
    cache = ViewMapperCache([_name_view("CogniteAsset")])
    engine = AsyncEngine.from_user_token(
        user_token="user-token",
        project="project",
        cluster="api",
        data_model_id=DATA_MODEL_ID,
        view_mapper_cache=cache,
    )

    assert engine._engine._cognite_adapter._view_mapper is cache


def _name_view(external_id: str) -> View:
    container = ContainerId("cdf_cdm", external_id)
    return View(
        space="cdf_cdm",
        external_id=external_id,
        version="v1",
        properties={
            "name": MappedProperty(
                container=container,
                container_property_identifier="name",
                type=Text(),
                nullable=False,
                immutable=False,
                auto_increment=False,
            )
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
