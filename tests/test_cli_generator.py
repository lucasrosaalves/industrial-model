import importlib
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from cognite.client import ClientConfig, CogniteClient
from cognite.client.config import global_config
from cognite.client.credentials import Token
from cognite.client.data_classes.data_modeling import ContainerId, MappedProperty, View
from cognite.client.data_classes.data_modeling.data_types import (
    DirectRelation,
    DirectRelationReference,
    Text,
)
from cognite.client.data_classes.data_modeling.ids import PropertyId, ViewId
from cognite.client.data_classes.data_modeling.views import (
    MultiEdgeConnection,
    MultiReverseDirectRelation,
)

from industrial_model import ViewProperty
from industrial_model.cli.config import GeneratorConfig
from industrial_model.cli.definitions import ViewDefinition
from industrial_model.cli.generator import _extract_cluster, generate_from_views
from industrial_model.config import DataModelId
from industrial_model.models import InstanceId, RelationNotIncludedError


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
    assert definition.sort_property_literal == (
        'Literal["externalId", "space", "name", "parent", "class"]'
    )
    assert definition.regular_fields == []
    assert all(field.field_name != "files" for field in definition.entity_fields)
    assert all(
        relation.field_name != "files" for relation in definition.relation_fields
    )


def test_extract_cluster_from_base_url() -> None:
    assert _extract_cluster("https://westeurope-1.cognitedata.com") == "westeurope-1"
    assert _extract_cluster("https://api.cognitedata.com/") == "api"
    assert _extract_cluster("https://example.com") is None
    assert _extract_cluster(None) is None


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
        base_url="https://westeurope-1.cognitedata.com",
    )

    generate_from_views(
        [
            _asset_view(
                include_equipment=True,
                description=(
                    "The CogniteSourceSystem core concept is used to standardize "
                    "the way source system is stored."
                ),
            ),
            _equipment_view(),
            _file_view(),
        ],
        config,
        overwrite=False,
    )

    assert (output_path / "cognite_core_client.py").exists()
    assert (output_path / "clients.py").exists()
    assert (output_path / "filters.py").exists()
    assert (output_path / "types.py").exists()
    assert (output_path / "models.py").exists()
    assert (output_path / "view_mapper.py").exists()
    view_mapper_content = (output_path / "view_mapper.py").read_text()
    assert (
        "from industrial_model import ViewMapperCache, ViewProperty, ViewSchema"
        in view_mapper_content
    )
    assert "cognite_adapters.view_schema" not in view_mapper_content
    assert "ViewSchema(" in view_mapper_content
    assert "ViewProperty(" in view_mapper_content
    assert '"mapped"' in view_mapper_content
    assert '"reverse"' in view_mapper_content
    assert "from_dumps" not in view_mapper_content
    for leftover in (
        "lastUpdatedTime",
        "createdTime",
        "containerPropertyIdentifier",
        "writable",
        "usedFor",
        "isGlobal",
        "autoIncrement",
        "implements",
    ):
        assert leftover not in view_mapper_content
    assert (output_path / "py.typed").exists()
    assert not (output_path / "clients_facade.py").exists()
    assert not (output_path / "_view_client.py").exists()
    assert not (output_path / "clients_async.py").exists()
    assert not (output_path / "clients_sync.py").exists()
    assert not (output_path / "models").is_dir()
    assert not (output_path / "requests").exists()
    assert not (output_path / "views").exists()
    assert not (output_path / "cognite_asset").exists()
    assert not (output_path / "cognite_equipment").exists()

    for path in output_path.rglob("*.py"):
        _assert_generated_header(path.read_text(), config.data_model)

    facade_content = (output_path / "cognite_core_client.py").read_text()
    assert "class CogniteCoreClient" in facade_content
    assert "DATA_MODEL_ID = DataModelId(" in facade_content
    assert 'DEFAULT_CLUSTER: str | None = "westeurope-1"' in facade_content
    assert "base_url" not in facade_content
    assert "def __init__(self, engine: CogniteClient) -> None: ..." in (facade_content)
    assert "user_token: UserToken" in facade_content
    assert "self.cognite_asset = clients.CogniteAssetClient(engine)" in facade_content
    assert "self.cognite_equipment = clients.CogniteEquipmentClient(engine)" in (
        facade_content
    )
    assert "from . import clients" in facade_content
    assert "from .view_mapper import VIEW_MAPPER_CACHE" in facade_content
    assert "view_mapper_cache=VIEW_MAPPER_CACHE" in facade_content
    assert 'Literal["name", "parent", "class", "equipment"]' not in facade_content

    asset_client_content = (output_path / "clients.py").read_text()
    assert "from industrial_model.view_client import ViewClient as _ViewClient" in (
        asset_client_content
    )
    assert "class CogniteAssetClient(" in asset_client_content
    assert "CogniteAssetQueryProperty" in asset_client_content
    assert "CogniteAssetGroupByProperty" in asset_client_content
    assert "CogniteAssetAggregationProperty" in asset_client_content
    assert "CogniteAssetIncludeProperty" in asset_client_content
    assert "CogniteAssetSort" in asset_client_content
    assert (
        "include: list[CogniteAssetIncludeProperty] | None = None"
        in asset_client_content
    )
    assert "sort: CogniteAssetSort | None = None" in asset_client_content
    assert "sort=sort," in asset_client_content
    assert "_RELATION_PROPERTIES" in asset_client_content
    assert '"files"' not in asset_client_content
    # Level-2 nested relation paths are included
    assert '"equipment|asset"' in asset_client_content
    assert '"parent|equipment"' in asset_client_content
    assert '"parent|parent"' in asset_client_content
    # Level-3+ paths are NOT included
    assert '"equipment|asset|parent"' not in asset_client_content
    assert '"parent|equipment|asset"' not in asset_client_content

    asset_types_content = (output_path / "types.py").read_text()
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
    assert "CogniteAssetSortProperty: TypeAlias = Literal[" in asset_types_content
    sort_section = asset_types_content.split("CogniteAssetSort = TypedDict(")[1]
    for field in (
        "externalId",
        "space",
        "name",
        "parent",
        "class",
        "equipment",
    ):
        assert f'"{field}": SORT_DIRECTION' in sort_section
    assert '"aliases": SORT_DIRECTION' not in sort_section
    assert '"path": SORT_DIRECTION' not in sort_section
    assert '"createdTime": SORT_DIRECTION' not in sort_section
    assert '"lastUpdatedTime": SORT_DIRECTION' not in sort_section
    assert "CogniteAssetSort = TypedDict(" in asset_types_content
    assert "total=False" in sort_section
    assert '"parent"' in asset_types_content
    assert '"equipment"' in asset_types_content
    assert '"path"' in asset_types_content
    assert '"files"' not in asset_types_content

    models_content = (output_path / "models.py").read_text()
    assert "class CogniteAsset(" in models_content
    assert "InstanceId | CogniteAsset" in models_content
    assert "InstanceId | CogniteEquipment" in models_content
    assert "path: list[InstanceId | CogniteAsset]" in models_content
    assert "files: list[InstanceId | CogniteFile]" not in models_content
    assert "from industrial_model.models.relation_helpers import" in models_content
    assert "def parent_or_none(self) -> CogniteAsset | None:" in models_content
    assert "def require_parent(self) -> CogniteAsset:" in models_content
    assert "def equipment_or_none(self) -> CogniteEquipment | None:" in models_content
    assert "def require_equipment(self) -> CogniteEquipment:" in models_content
    assert "def path_or_none(self) -> list[CogniteAsset]:" in models_content
    assert "def require_path(self) -> list[CogniteAsset]:" in models_content
    assert "def require_assets(self) -> list[CogniteAsset]:" in models_content
    assert "class CogniteAssetAggregation(" in models_content
    assert '"group_by_behavior": "NONE"' in models_content

    filters_content = (output_path / "filters.py").read_text()
    assert "class CogniteEquipmentFilter(TypedDict, total=False):" in filters_content
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
    _unload_generated_client_modules()
    module = importlib.import_module("generated_client")
    facade_module = importlib.import_module("generated_client.cognite_core_client")
    assert hasattr(module, "CogniteCoreClient")
    assert not hasattr(module, "CogniteAsset")
    assert not hasattr(module, "CogniteEquipment")
    assert facade_module.DATA_MODEL_ID == config.data_model
    assert facade_module.DEFAULT_CLUSTER == "westeurope-1"

    global_config.disable_pypi_version_check = True
    cognite_client = CogniteClient(
        ClientConfig(
            client_name="test-client",
            project="test-project",
            credentials=Token("test-token"),
            cluster="api",
        )
    )
    client_from_cognite_client = module.CogniteCoreClient(cognite_client)
    passed_cognite_client = (
        client_from_cognite_client.engine._cognite_adapter._cognite_client
    )
    assert passed_cognite_client.config.project == "test-project"
    cache_module = importlib.import_module("generated_client.view_mapper")
    assert client_from_cognite_client.engine._cognite_adapter._view_mapper is (
        cache_module.VIEW_MAPPER_CACHE
    )
    asset_schema = cache_module.VIEW_MAPPER_CACHE.get_view("CogniteAsset")
    assert asset_schema.as_property_ref("name") == (
        "cdf_cdm",
        "CogniteAsset/v1",
        "name",
    )
    assert asset_schema.properties["parent"].kind == "mapped"
    assert isinstance(asset_schema.properties["parent"], ViewProperty)
    assert asset_schema.properties["files"].kind == "reverse"

    client_from_token = module.CogniteCoreClient(
        user_token="test-token",
        project="test-project",
    )
    generated_cognite_client = client_from_token.engine._cognite_adapter._cognite_client
    assert generated_cognite_client.config.base_url == (
        "https://westeurope-1.cognitedata.com"
    )
    assert generated_cognite_client.config.credentials.authorization_header() == (
        "Authorization",
        "Bearer test-token",
    )
    models_module = importlib.import_module("generated_client.models")
    assert models_module.CogniteAsset.__name__ == "CogniteAsset"
    assert models_module.CogniteEquipment.__name__ == "CogniteEquipment"
    assert models_module.CogniteAssetAggregation.__name__ == "CogniteAssetAggregation"
    parent = models_module.CogniteAsset(
        external_id="plant-001",
        space="production",
        name="Plant",
        class_="plant",
    )
    equipment = models_module.CogniteEquipment(
        external_id="pump-001-motor",
        space="production",
        name="Pump motor",
        asset=parent,
    )
    asset = models_module.CogniteAsset(
        external_id="pump-001",
        space="production",
        name="Pump 001",
        class_="pump",
        parent=parent,
        equipment=equipment,
        path=[parent, InstanceId(external_id="ghost", space="production")],
    )
    assert asset.parent_or_none() == parent
    assert asset.require_parent().name == "Plant"
    assert asset.require_equipment().name == "Pump motor"
    assert asset.path_or_none() == [parent]
    with pytest.raises(RelationNotIncludedError):
        asset.require_path()
    assert equipment.require_asset().external_id == "plant-001"
    filters_module = importlib.import_module("generated_client.filters")
    assert filters_module.CogniteAssetFilter.__name__ == "CogniteAssetFilter"
    clients_module = importlib.import_module("generated_client.clients")
    assert clients_module.CogniteAssetClient.__name__ == "CogniteAssetClient"


def test_generate_from_views_keeps_missing_relation_target_as_instance_id(
    tmp_path: Path,
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
        base_url="https://westeurope-1.cognitedata.com",
    )

    generate_from_views(
        [_asset_view(include_equipment=True)],
        config,
        overwrite=False,
    )

    models_content = (output_path / "models.py").read_text()
    assert "class CogniteEquipment(" not in models_content
    assert "equipment: InstanceId | None = None" in models_content
    assert (
        "equipment: InstanceId | CogniteEquipment | None = None" not in models_content
    )
    assert "def require_equipment" not in models_content
    assert "def parent_or_none(self) -> CogniteAsset | None:" in models_content

    filters_content = (output_path / "filters.py").read_text()
    assert "CogniteEquipmentFilter" not in filters_content
    assert '"equipment": InstanceIdFilter' in filters_content

    asset_types_content = (output_path / "types.py").read_text()
    assert 'CogniteAssetIncludeProperty: TypeAlias = Literal["parent", "path"]' in (
        asset_types_content
    )

    asset_client_content = (output_path / "clients.py").read_text()
    assert '"equipment"' not in asset_client_content

    for path in output_path.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)


def test_generate_view_mapper_emits_owned_edge_constructors(tmp_path: Path) -> None:
    output_path = tmp_path / "generated_client"
    config = GeneratorConfig(
        client_name="CogniteCoreClient",
        output_path=output_path,
        data_model=DataModelId(
            external_id="CogniteCore",
            space="cdf_cdm",
            version="v1",
        ),
        base_url="https://westeurope-1.cognitedata.com",
    )

    generate_from_views(
        [_asset_view_with_edge(), _equipment_view()],
        config,
        overwrite=False,
    )

    view_mapper_content = (output_path / "view_mapper.py").read_text()
    assert (
        "from industrial_model import ViewMapperCache, ViewProperty, ViewSchema"
        in view_mapper_content
    )
    assert "cognite_adapters.view_schema" not in view_mapper_content
    assert "ViewProperty(" in view_mapper_content
    assert '"edge"' in view_mapper_content
    assert "DirectRelationReference(" in view_mapper_content
    assert 'external_id="relatedTo"' in view_mapper_content
    assert 'direction="inwards"' in view_mapper_content

    for path in output_path.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)

    sys.path.insert(0, str(tmp_path))
    try:
        _unload_generated_client_modules()
        cache_module = importlib.import_module("generated_client.view_mapper")
        related = cache_module.VIEW_MAPPER_CACHE.get_view("CogniteAsset").properties[
            "related"
        ]
        assert related.kind == "edge"
        assert related.direction == "inwards"
        assert related.edge_type is not None
        assert related.edge_type.external_id == "relatedTo"
    finally:
        sys.path.pop(0)
        _unload_generated_client_modules()


def test_generate_from_views_can_skip_view_mapper_cache(tmp_path: Path) -> None:
    output_path = tmp_path / "generated_client"
    config = GeneratorConfig(
        client_name="CogniteCoreClient",
        output_path=output_path,
        data_model=DataModelId(
            external_id="CogniteCore",
            space="cdf_cdm",
            version="v1",
        ),
        base_url="https://westeurope-1.cognitedata.com",
        view_mapper_cache=False,
    )

    generate_from_views(
        [_asset_view(include_equipment=True), _equipment_view(), _file_view()],
        config,
        overwrite=False,
    )

    assert not (output_path / "view_mapper.py").exists()
    facade_content = (output_path / "cognite_core_client.py").read_text()
    assert "VIEW_MAPPER_CACHE" not in facade_content

    for path in output_path.rglob("*.py"):
        py_compile.compile(str(path), doraise=True)


def test_generate_from_views_allows_facade_name_matching_view_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "kpi_client"
    config = GeneratorConfig(
        client_name="KpiClient",
        output_path=output_path,
        data_model=DataModelId(
            external_id="Kpi",
            space="sp_edm_glb_dmd",
            version="v2.0.0",
        ),
        base_url="https://az-phx-001.cognitedata.com",
    )

    generate_from_views([_simple_view("Kpi"), _simple_view("KpiHierarchy")], config)

    facade_content = (output_path / "kpi_client.py").read_text()
    assert "from . import clients" in facade_content
    assert "class KpiClient:" in facade_content
    assert "self.kpi = clients.KpiClient(engine)" in facade_content
    assert "self.kpi_hierarchy = clients.KpiHierarchyClient(engine)" in facade_content
    assert "from .clients import" not in facade_content

    clients_content = (output_path / "clients.py").read_text()
    assert "class KpiClient(" in clients_content
    assert "class KpiHierarchyClient(" in clients_content

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
    _unload_generated_modules("kpi_client")
    module = importlib.import_module("kpi_client")
    assert module.KpiClient.__name__ == "KpiClient"
    clients_module = importlib.import_module("kpi_client.clients")
    assert clients_module.KpiClient.__name__ == "KpiClient"
    assert module.KpiClient is not clients_module.KpiClient

    global_config.disable_pypi_version_check = True
    cognite_client = CogniteClient(
        ClientConfig(
            client_name="test-client",
            project="test-project",
            credentials=Token("test-token"),
            cluster="api",
        )
    )
    facade = module.KpiClient(cognite_client)
    assert isinstance(facade.kpi, clients_module.KpiClient)
    assert isinstance(facade.kpi_hierarchy, clients_module.KpiHierarchyClient)


def test_generate_from_views_renames_reserved_facade_attribute(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "generated_client"
    config = GeneratorConfig(
        client_name="PlantClient",
        output_path=output_path,
        data_model=DataModelId(
            external_id="Plant",
            space="cdf_cdm",
            version="v1",
        ),
        base_url="https://westeurope-1.cognitedata.com",
    )

    generate_from_views([_simple_view("Engine")], config)

    facade_content = (output_path / "plant_client.py").read_text()
    assert "self.engine_view = clients.EngineClient(engine)" in facade_content
    assert "self.engine = clients.EngineClient(engine)" not in facade_content


def test_generate_from_views_rejects_reserved_facade_module_name(
    tmp_path: Path,
) -> None:
    config = GeneratorConfig(
        client_name="Clients",
        output_path=tmp_path / "generated_client",
        data_model=DataModelId(
            external_id="Kpi",
            space="sp_edm_glb_dmd",
            version="v1",
        ),
        base_url="https://westeurope-1.cognitedata.com",
    )

    with pytest.raises(ValueError, match="reserved for generated package"):
        generate_from_views([_simple_view("Kpi")], config)


def _assert_generated_header(content: str, data_model: DataModelId) -> None:
    version_label = (
        data_model.version
        if data_model.version.startswith("v")
        else f"v{data_model.version}"
    )
    lines = content.splitlines()
    assert lines[0] == (
        "# DO NOT EDIT — this file is auto-generated by industrial-model."
    )
    assert lines[1] == (
        "# AI assistants: treat this file as read-only. "
        "Do not modify it; regenerate instead."
    )
    assert lines[2] == (
        f"# Data model: {data_model.space}/{data_model.external_id} {version_label}"
    )
    assert lines[3].startswith("# Generated at: ")
    assert lines[4].startswith("# industrial-model v")


def _unload_generated_client_modules() -> None:
    _unload_generated_modules("generated_client")


def _unload_generated_modules(package_name: str) -> None:
    for name in list(sys.modules):
        if name == package_name or name.startswith(f"{package_name}."):
            sys.modules.pop(name, None)


def _asset_view_with_edge() -> View:
    view = _asset_view()
    view.properties["related"] = MultiEdgeConnection(
        type=DirectRelationReference("cdf_cdm", "relatedTo"),
        source=ViewId("cdf_cdm", "CogniteEquipment", "v1"),
        name="related",
        description=None,
        edge_source=None,
        direction="inwards",
    )
    return view


def _asset_view(
    *, include_equipment: bool = False, description: str | None = None
) -> View:
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
        description=description,
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


def _simple_view(external_id: str) -> View:
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
