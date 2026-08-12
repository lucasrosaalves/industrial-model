from cognite.client.data_classes.data_modeling import (
    ContainerId,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.data_types import DirectRelation, Text

from industrial_model.cognite_adapters.sort_mapper import SortMapper
from industrial_model.statements.expressions import Column

_ROOT_VIEW = View(
    space="cdf_cdm",
    external_id="CogniteAsset",
    version="v1",
    properties={
        "name": MappedProperty(
            container=ContainerId("space", "container"),
            container_property_identifier="name",
            type=Text(),
            nullable=True,
            immutable=False,
            auto_increment=False,
            source=None,
        ),
        "parent": MappedProperty(
            container=ContainerId("space", "container"),
            container_property_identifier="parent",
            type=DirectRelation(),
            nullable=True,
            immutable=False,
            auto_increment=False,
            source=ViewId("space", "CogniteAsset", "v1"),
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


def test_nulls_first_false_for_ascending_scalar_sort() -> None:
    mapper = SortMapper()

    result = mapper.map([(Column("name"), "ascending")], _ROOT_VIEW)

    assert result[0].nulls_first is False


def test_nulls_first_true_for_descending_scalar_sort() -> None:
    mapper = SortMapper()

    result = mapper.map([(Column("name"), "descending")], _ROOT_VIEW)

    assert result[0].nulls_first is True


def test_nulls_first_false_for_ascending_direct_relation_sort() -> None:
    mapper = SortMapper()

    result = mapper.map([(Column("parent"), "ascending")], _ROOT_VIEW)

    assert result[0].nulls_first is False


def test_nulls_first_true_for_descending_direct_relation_sort() -> None:
    mapper = SortMapper()

    result = mapper.map([(Column("parent"), "descending")], _ROOT_VIEW)

    assert result[0].nulls_first is True
