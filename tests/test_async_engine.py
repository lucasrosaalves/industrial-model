import asyncio

from industrial_model import (
    AggregatedViewInstance,
    InstanceId,
    PaginatedResult,
    ViewInstanceConfig,
    aggregate,
    col,
    search,
    select,
)

from .hubs import generate_async_engine, generate_engine
from .models import CogniteAsset, CogniteDescribable, CogniteEquipment


def test_engine_query_async_describable() -> None:
    async def run() -> None:
        engine = generate_engine()

        select_statements = [
            select(CogniteDescribable).limit(10),
            select(CogniteDescribable).where(CogniteDescribable.name == "test"),
        ]

        for statement in select_statements:
            result = await engine.query_async(statement)
            assert isinstance(result, PaginatedResult)

    asyncio.run(run())


def test_engine_query_all_pages_async_equipment() -> None:
    async def run() -> None:
        engine = generate_engine()

        statement = (
            select(CogniteEquipment)
            .where(col("externalId").in_(["__industrial_model_async_no_match__"]))
            .limit(10)
        )

        result = await engine.query_all_pages_async(statement)
        assert isinstance(result, list)

    asyncio.run(run())


def test_engine_search_async_asset() -> None:
    async def run() -> None:
        engine = generate_engine()

        asset_result = await engine.search_async(
            search(CogniteAsset).where(
                col(CogniteAsset.path).contains_any_(
                    [{"externalId": "CHILD-456", "space": "cdf_cdm"}]
                )
            )
        )
        assert isinstance(asset_result, list)

        describable_result = await engine.search_async(
            search(CogniteDescribable).limit(10)
        )
        assert isinstance(describable_result, list)

    asyncio.run(run())


def test_engine_aggregate_async() -> None:
    async def run() -> None:
        engine = generate_engine()

        class CountAssetByParent(AggregatedViewInstance):
            view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
            parent: InstanceId

        statement = aggregate(CountAssetByParent, "count").where(
            col("description").exists_()
        )

        result = await engine.aggregate_async(statement)
        assert isinstance(result, list)

    asyncio.run(run())


def test_async_engine_query_async_describable() -> None:
    async def run() -> None:
        async_engine = generate_async_engine()

        select_statements = [
            select(CogniteDescribable).limit(10),
            select(CogniteDescribable).where(CogniteDescribable.name == "test"),
        ]

        for statement in select_statements:
            result = await async_engine.query_async(statement)
            assert isinstance(result, PaginatedResult)

    asyncio.run(run())
