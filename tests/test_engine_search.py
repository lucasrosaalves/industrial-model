from industrial_model import InstanceId, col, search

from .hubs import generate_engine
from .models import CogniteAsset, CogniteAssetType, CogniteDescribable, CogniteEquipment


def test_engine_search() -> None:
    engine = generate_engine()

    search_statements = [
        search(CogniteDescribable).limit(10),
        search(CogniteDescribable).where(CogniteDescribable.name == "test"),
        search(CogniteAssetType)
        .limit(10)
        .where(CogniteAssetType.code == "TESTING_123")
        .asc(CogniteAssetType.code),
        search(CogniteEquipment).where(col(CogniteEquipment.asset).exists_()).limit(10),
        search(CogniteAsset).where(
            col(CogniteAsset.path).contains_any_(
                [InstanceId(external_id="CHILD-456", space="cdf_cdm")]
            )
        ),
    ]

    for statement in search_statements:
        result = engine.search(statement)
        assert isinstance(result, list)
