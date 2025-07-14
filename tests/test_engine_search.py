from industrial_model import col, search

from .hubs import generate_engine
from .models import CogniteAsset, CogniteAssetType, CogniteDescribable, CogniteEquipment


def test_engine_search_describable() -> None:
    engine = generate_engine()

    search_statements = [
        search(CogniteDescribable).limit(10),
        search(CogniteDescribable).where(CogniteDescribable.name == "test"),
    ]

    for statement in search_statements:
        result = engine.search(statement)
        assert isinstance(result, list)


def test_engine_search_asset_type() -> None:
    engine = generate_engine()

    search_statements = [
        search(CogniteAssetType).limit(10).where(CogniteAssetType.code == "TESTING_123")
    ]

    for statement in search_statements:
        result = engine.search(statement)
        assert isinstance(result, list)


def test_engine_search_equipment() -> None:
    engine = generate_engine()

    search_statements = [
        search(CogniteEquipment).where(col(CogniteEquipment.asset).exists_()).limit(10),
    ]

    for statement in search_statements:
        result = engine.search(statement)
        assert isinstance(result, list)


def test_engine_search_asset() -> None:
    engine = generate_engine()

    search_statements = [
        search(CogniteAsset).where(
            col(CogniteAsset.path).contains_any_(
                [{"externalId": "CHILD-456", "space": "cdf_cdm"}]
            )
        ),
    ]

    for statement in search_statements:
        result = engine.search(statement)
        assert isinstance(result, list)
