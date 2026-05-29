from cognite.client.data_classes.data_modeling import (
    ContainerId,
    MappedProperty,
    View,
)
from cognite.client.data_classes.data_modeling.data_types import Text

from industrial_model import AggregatedViewInstance, ViewInstanceConfig, aggregate
from industrial_model.cognite_adapters.aggregation_mapper import AggregationMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapper


class AssetAggregationDefault(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="CogniteAsset")
    name: str | None = None


class AssetAggregationNoDefaultGroupBy(AggregatedViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="CogniteAsset",
        group_by_behavior="NONE",
    )
    name: str | None = None


class FakeViewMapper(ViewMapper):
    def __init__(self, views: dict[str, View]) -> None:
        self._views = views

    def get_view(self, view_external_id: str) -> View:
        return self._views[view_external_id]


def test_aggregation_mapper_defaults_to_grouping_by_model_fields() -> None:
    query = AggregationMapper(_fake_view_mapper()).map(
        aggregate(AssetAggregationDefault)
    )

    assert query.group_by_columns == ["name"]


def test_aggregation_mapper_can_disable_default_grouping() -> None:
    query = AggregationMapper(_fake_view_mapper()).map(
        aggregate(AssetAggregationNoDefaultGroupBy)
    )

    assert query.group_by_columns == []


def test_aggregation_mapper_explicit_group_by_overrides_config() -> None:
    query = AggregationMapper(_fake_view_mapper()).map(
        aggregate(AssetAggregationNoDefaultGroupBy).group_by("name")
    )

    assert query.group_by_columns == ["name"]


def _fake_view_mapper() -> FakeViewMapper:
    return FakeViewMapper(
        {
            "CogniteAsset": View(
                space="space",
                external_id="CogniteAsset",
                version="version",
                properties={
                    "name": _mapped_property("name"),
                },
                last_updated_time=0,
                created_time=0,
                description=None,
                name=None,
                filter=None,
                implements=None,
                writable=True,
                is_global=False,
                used_for="node",
            )
        }
    )


def _mapped_property(identifier: str) -> MappedProperty:
    return MappedProperty(
        container=ContainerId("space", "container"),
        container_property_identifier=identifier,
        type=Text(),
        nullable=True,
        immutable=False,
        auto_increment=False,
        source=None,
    )
