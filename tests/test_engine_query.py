from industrial_model import InstanceId, PaginatedResult, col, select

from .hubs import generate_engine
from .models import CogniteAsset, CogniteAssetType, CogniteDescribable, CogniteEquipment


def test_engine_query() -> None:
    engine = generate_engine()

    select_statements = [
        select(CogniteDescribable).limit(10),
        select(CogniteDescribable).where(CogniteDescribable.name == "test"),
        select(CogniteAssetType)
        .limit(10)
        .where(CogniteAssetType.code == "TESTING_123")
        .asc(CogniteAssetType.code),
        select(CogniteEquipment).where(col(CogniteEquipment.asset).exists_()).limit(10),
        select(CogniteAsset).where(
            col(CogniteAsset.parent).nested_(CogniteAsset.external_id == "PARENT-123")
        ),
        select(CogniteAsset).where(
            col(CogniteAsset.path).contains_any_(
                [InstanceId(external_id="CHILD-456", space="cdf_cdm")]
            )
        ),
    ]

    for statement in select_statements:
        result = engine.query(statement)
        assert isinstance(result, PaginatedResult)
