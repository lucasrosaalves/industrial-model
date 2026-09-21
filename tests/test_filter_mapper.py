import pytest
from cognite.client.data_classes.data_modeling import ViewId
from cognite.client.data_classes.data_modeling.data_types import DirectRelationReference

from industrial_model import ViewProperty, ViewSchema
from industrial_model.cognite_adapters.filter_mapper import FilterMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapperCache
from industrial_model.constants import NESTED_SEP
from industrial_model.statements import col
from industrial_model.statements.expressions import LeafExpression


def test_map_edges_rejects_non_edge_property() -> None:
    schema = ViewSchema(
        space="space",
        external_id="Asset",
        version="v1",
        properties={"name": ViewProperty("mapped")},
    )
    mapper = FilterMapper(ViewMapperCache([schema]))

    with pytest.raises(ValueError, match="name is not an edge"):
        mapper.map_edges(
            [(col("name"), [LeafExpression("name", "==", "pump")])],
            schema,
            NESTED_SEP,
        )


def test_map_edges_rejects_edge_without_source() -> None:
    schema = ViewSchema(
        space="space",
        external_id="Asset",
        version="v1",
        properties={
            "related": ViewProperty(
                "edge",
                edge_type=DirectRelationReference("space", "relatedTo"),
            )
        },
    )
    mapper = FilterMapper(ViewMapperCache([schema]))

    with pytest.raises(ValueError, match="related is missing a source"):
        mapper.map_edges(
            [(col("related"), [LeafExpression("name", "==", "pump")])],
            schema,
            NESTED_SEP,
        )


def test_map_edges_maps_filters_on_edge_target_view() -> None:
    asset = ViewSchema(
        space="space",
        external_id="Asset",
        version="v1",
        properties={
            "related": ViewProperty(
                "edge",
                source=ViewId("space", "Equipment", "v1"),
                edge_type=DirectRelationReference("space", "relatedTo"),
            )
        },
    )
    equipment = ViewSchema(
        space="space",
        external_id="Equipment",
        version="v1",
        properties={"name": ViewProperty("mapped")},
    )
    mapper = FilterMapper(ViewMapperCache([asset, equipment]))

    result = mapper.map_edges(
        [(col("related"), [LeafExpression("name", "==", "pump")])],
        asset,
        NESTED_SEP,
    )

    assert list(result) == [f"Asset{NESTED_SEP}related"]
    assert result[f"Asset{NESTED_SEP}related"][0].dump() == {
        "equals": {
            "property": ("space", "Equipment/v1", "name"),
            "value": "pump",
        }
    }
