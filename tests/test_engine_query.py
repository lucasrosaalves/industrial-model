from industrial_model import Engine, PaginatedResult, col, select

from .hubs import generate_engine
from .models import CogniteAsset, CogniteAssetType, CogniteDescribable, CogniteEquipment


def test_engine_query_describable() -> None:
    engine = generate_engine()

    select_statements = [
        select(CogniteDescribable).limit(10),
        select(CogniteDescribable).where(CogniteDescribable.name == "test"),
    ]

    for statement in select_statements:
        result = engine.query(statement)
        assert isinstance(result, PaginatedResult)


def test_engine_query_asset_type() -> None:
    engine = generate_engine()

    select_statements = [
        select(CogniteAssetType)
        .limit(10)
        .where(CogniteAssetType.code == "TESTING_123")
        .asc(CogniteAssetType.code),
    ]

    for statement in select_statements:
        result = engine.query(statement)
        assert isinstance(result, PaginatedResult)


def test_engine_query_equipment() -> None:
    engine = generate_engine()

    select_statements = [
        select(CogniteEquipment).where(col(CogniteEquipment.asset).exists_()).limit(10),
        select(CogniteEquipment)
        .where(col(CogniteEquipment.asset).exists_() & col("externalId").in_(["123"]))
        .limit(10),
    ]

    for statement in select_statements:
        result = engine.query(statement)
        assert isinstance(result, PaginatedResult)


def test_engine_query_asset() -> None:
    engine = generate_engine()

    spaces = _get_spaces(engine)
    select_statements = [
        select(CogniteAsset)
        .where(
            col(CogniteAsset.space).in_(spaces),
            col(CogniteAsset.parent).nested_(CogniteAsset.external_id == "PARENT-123"),
        )
        .limit(1),
        select(CogniteAsset)
        .where(
            col(CogniteAsset.space).in_(spaces),
            col(CogniteAsset.path).contains_any_(
                [{"externalId": "CHILD-456", "space": "cdf_cdm"}]
            ),
        )
        .limit(1),
    ]

    for statement in select_statements:
        result = engine.query(statement)
        assert isinstance(result, PaginatedResult)


def _get_spaces(engine: Engine) -> list[str]:
    return engine._cognite_adapter._cognite_client.data_modeling.spaces.list(1).as_ids()
