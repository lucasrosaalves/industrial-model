import importlib
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from cognite.client.data_classes.data_modeling import ContainerId, MappedProperty, View
from cognite.client.data_classes.data_modeling.data_types import DirectRelation, Text
from cognite.client.data_classes.data_modeling.ids import PropertyId, ViewId
from cognite.client.data_classes.data_modeling.views import MultiReverseDirectRelation

from industrial_model.cli.config import GeneratorConfig
from industrial_model.cli.definitions import ViewDefinition
from industrial_model.cli.generator import generate_from_views
from industrial_model.config import DataModelId


def test_view_definition_maps_cdf_properties_to_model_fields() -> None:
    definition = ViewDefinition.from_view(_asset_view(), None)

    assert definition.view_name == "CogniteAsset"
    assert definition.view_config == (
        'view_config = {"view_external_id": "CogniteAsset"}'
    )
    assert [field.field_name for field in definition.search_fields] == [
        "name",
        "aliases",
        "parent",
        "class_",
    ]
    assert str(definition.search_fields[1]) == (
        "aliases: list[str] = Field(default_factory=list)"
    )
    assert str(definition.search_fields[2]) == "parent: InstanceId | None = None"
    assert str(definition.search_fields[3]) == 'class_: str = Field(alias="class")'
    assert definition.regular_fields == []
    assert all(field.field_name != "files" for field in definition.entity_fields)
    assert all(
        relation.field_name != "files" for relation in definition.relation_fields
    )


def test_generate_from_views_writes_compileable_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "generated_client"
    config = GeneratorConfig(
        client_name="CogniteCoreClient",
        output_path=output_path,
        data_model=DataModelId(
            external_id="CogniteCore",
            space="cdf_cdm",
            version="v1",
        ),
    )

    generate_from_views(
        [_asset_view(include_equipment=True), _equipment_view(), _file_view()],
        config,
        overwrite=False,
    )

    assert (output_path / "cognite_core_client.py").exists()
    assert not (output_path / "clients_facade.py").exists()
    assert not (output_path / "clients.py").exists()
    assert (output_path / "_view_client.py").exists()
    assert not (output_path / "clients_async.py").exists()
    assert not (output_path / "clients_sync.py").exists()
    assert not (output_path / "models").exists()
    assert not (output_path / "requests").exists()
    assert not (output_path / "views").exists()
    assert (output_path / "cognite_asset" / "client.py").exists()
    assert (output_path / "cognite_asset" / "models.py").exists()
    assert (output_path / "cognite_asset" / "filters.py").exists()
    assert (output_path / "cognite_asset" / "types.py").exists()

    view_client_content = (output_path / "_view_client.py").read_text()
    assert "class ViewClient" in view_client_content
    assert "def query(" in view_client_content
    assert "async def query_async(" in view_client_content
    assert (
        "query_properties: list[_TQueryProperty] | None = None" in view_client_content
    )
    assert "group_by_properties: list[_TGroupBy] | None = None" in view_client_content
    assert (
        "aggregation_property: _TAggregationProperty | None = None"
        in view_client_content
    )
    assert "DUMMY_AGGREGATION_MAKER" not in view_client_content
    assert "query_complete" not in view_client_content

    facade_content = (output_path / "cognite_core_client.py").read_text()
    assert "class CogniteCoreClient" in facade_content
    assert "self.cognite_asset = CogniteAssetClient(engine)" in facade_content
    assert "self.cognite_equipment = CogniteEquipmentClient(engine)" in facade_content
    assert 'Literal["name", "parent", "class", "equipment"]' not in facade_content

    asset_client_content = (output_path / "cognite_asset" / "client.py").read_text()
    assert "class CogniteAssetClient(" in asset_client_content
    assert "CogniteAssetQueryProperty" in asset_client_content
    assert "CogniteAssetGroupByProperty" in asset_client_content
    assert "CogniteAssetAggregationProperty" in asset_client_content
    assert "CogniteAssetIncludeProperty" in asset_client_content
    assert (
        "include: list[CogniteAssetIncludeProperty] | None = None"
        in asset_client_content
    )
    assert "_RELATION_PROPERTIES" in asset_client_content
    assert '"files"' not in asset_client_content
    # Level-2 nested relation paths are included
    assert '"equipment|asset"' in asset_client_content
    assert '"parent|equipment"' in asset_client_content
    assert '"parent|parent"' in asset_client_content
    # Level-3+ paths are NOT included
    assert '"equipment|asset|parent"' not in asset_client_content
    assert '"parent|equipment|asset"' not in asset_client_content

    asset_types_content = (output_path / "cognite_asset" / "types.py").read_text()
    assert (
        'CogniteAssetQueryProperty: TypeAlias = Literal["name", "aliases", "class"]'
        in asset_types_content
    )
    assert (
        "CogniteAssetGroupByProperty: TypeAlias = "
        'Literal["name", "parent", "class", "equipment"]' in asset_types_content
    )
    assert "CogniteAssetAggregationProperty: TypeAlias = Literal[" in (
        asset_types_content
    )
    assert (
        '"externalId", "space", "name", "parent", "class", "equipment"'
        in asset_types_content
    )
    assert "CogniteAssetIncludeProperty: TypeAlias = Literal[" in asset_types_content
    assert '"parent"' in asset_types_content
    assert '"equipment"' in asset_types_content
    assert '"path"' in asset_types_content
    assert '"files"' not in asset_types_content

    assert (output_path / "models.py").exists()
    assert (output_path / "py.typed").exists()
    models_content = (output_path / "models.py").read_text()
    assert "class CogniteAsset(" in models_content
    assert "InstanceId | CogniteAsset" in models_content
    assert "InstanceId | CogniteEquipment" in models_content
    assert "path: list[InstanceId | CogniteAsset]" in models_content
    assert "files: list[InstanceId | CogniteFile]" not in models_content

    view_models_content = (output_path / "cognite_asset" / "models.py").read_text()
    assert "from ..models import CogniteAsset" in view_models_content
    assert "class CogniteAssetAggregation(" in view_models_content
    assert '"group_by_behavior": "NONE"' in view_models_content

    filters_content = (output_path / "cognite_asset" / "filters.py").read_text()
    assert (
        "from ..cognite_equipment.filters import CogniteEquipmentFilter"
        in filters_content
    )
    assert "CogniteAssetFilter = TypedDict(" in filters_content
    assert '"name": StringFilter' in filters_content
    assert '"parent": "InstanceIdFilter | CogniteAssetFilter"' in filters_content
    assert '"equipment": "InstanceIdFilter | CogniteEquipmentFilter"' in (
        filters_content
    )
    assert '"path": InstanceIdListFilter' in filters_content
    assert '"path": "InstanceIdListFilter | CogniteAssetFilter"' not in filters_content
    assert '"externalId": StringFilter' in filters_content
    assert '"class": StringFilter' in filters_content
    assert '"OR": "list[CogniteAssetFilter]"' in filters_content
    assert '"NOT": "CogniteAssetFilter"' in filters_content
    assert "COGNITE_ASSET_FIELDS" not in filters_content

    for path in output_path.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)

    mypy_result = subprocess.run(
        [sys.executable, "-m", "mypy", str(output_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert mypy_result.returncode == 0, mypy_result.stdout + mypy_result.stderr

    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("generated_client", None)
    module = importlib.import_module("generated_client")
    assert hasattr(module, "CogniteCoreClient")
    assert not hasattr(module, "CogniteAsset")
    assert not hasattr(module, "CogniteEquipment")
    models_module = importlib.import_module("generated_client.models")
    assert models_module.CogniteAsset.__name__ == "CogniteAsset"
    assert models_module.CogniteEquipment.__name__ == "CogniteEquipment"


def _asset_view(*, include_equipment: bool = False) -> View:
    container = ContainerId("cdf_cdm", "CogniteAsset")
    view_id = ViewId("cdf_cdm", "CogniteAsset", "v1")
    equipment_view_id = ViewId("cdf_cdm", "CogniteEquipment", "v1")
    file_view_id = ViewId("cdf_cdm", "CogniteFile", "v1")
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
        "class": MappedProperty(
            container=container,
            container_property_identifier="class",
            type=Text(),
            nullable=False,
            immutable=False,
            auto_increment=False,
        ),
        "files": MultiReverseDirectRelation(
            source=file_view_id,
            through=PropertyId(file_view_id, "assets"),
        ),
    }
    if include_equipment:
        properties["equipment"] = MappedProperty(
            container=container,
            container_property_identifier="equipment",
            type=DirectRelation(),
            nullable=True,
            immutable=False,
            auto_increment=False,
            source=equipment_view_id,
        )
        properties["path"] = MappedProperty(
            container=container,
            container_property_identifier="path",
            type=DirectRelation(is_list=True),
            nullable=False,
            immutable=False,
            auto_increment=False,
            source=view_id,
        )

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


def _equipment_view() -> View:
    container = ContainerId("cdf_cdm", "CogniteEquipment")
    asset_view_id = ViewId("cdf_cdm", "CogniteAsset", "v1")

    return View(
        space="cdf_cdm",
        external_id="CogniteEquipment",
        version="v1",
        properties={
            "name": MappedProperty(
                container=container,
                container_property_identifier="name",
                type=Text(),
                nullable=False,
                immutable=False,
                auto_increment=False,
            ),
            "asset": MappedProperty(
                container=container,
                container_property_identifier="asset",
                type=DirectRelation(),
                nullable=True,
                immutable=False,
                auto_increment=False,
                source=asset_view_id,
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


def _file_view() -> View:
    container = ContainerId("cdf_cdm", "CogniteFile")
    asset_view_id = ViewId("cdf_cdm", "CogniteAsset", "v1")

    return View(
        space="cdf_cdm",
        external_id="CogniteFile",
        version="v1",
        properties={
            "name": MappedProperty(
                container=container,
                container_property_identifier="name",
                type=Text(),
                nullable=False,
                immutable=False,
                auto_increment=False,
            ),
            "assets": MappedProperty(
                container=container,
                container_property_identifier="assets",
                type=DirectRelation(is_list=True),
                nullable=False,
                immutable=False,
                auto_increment=False,
                source=asset_view_id,
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
