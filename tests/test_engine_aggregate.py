from industrial_model import (
    AggregatedViewInstance,
    InstanceId,
    ViewInstanceConfig,
    aggregate,
    col,
)

from .hubs import generate_engine


def test_engine_aggregate() -> None:
    engine = generate_engine()

    class CountAssetByParent(AggregatedViewInstance):
        view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
        parent: InstanceId

    statement = aggregate(CountAssetByParent, "count").where(
        col("description").exists_()
    )

    result = engine.aggregate(statement)

    assert isinstance(result, list)
