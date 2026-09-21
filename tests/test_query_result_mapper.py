import pytest
from cognite.client.data_classes.data_modeling import Node, ViewId
from cognite.client.data_classes.data_modeling.instances import Properties

from industrial_model import ViewProperty, ViewSchema
from industrial_model.cognite_adapters.query_result_mapper import QueryResultMapper
from industrial_model.cognite_adapters.view_mapper import ViewMapperCache


def test_query_result_mapper_raises_for_reverse_missing_through() -> None:
    asset_id = ViewId("space", "Asset", "v1")
    mapper = QueryResultMapper(
        ViewMapperCache(
            [
                ViewSchema(
                    space="space",
                    external_id="Asset",
                    version="v1",
                    properties={
                        "files": ViewProperty(
                            "reverse",
                            source=ViewId("space", "File", "v1"),
                        )
                    },
                ),
                ViewSchema(
                    space="space",
                    external_id="File",
                    version="v1",
                    properties={"name": ViewProperty("mapped")},
                ),
            ]
        )
    )
    node = Node(
        space="space",
        external_id="asset-1",
        version=1,
        last_updated_time=0,
        created_time=0,
        deleted_time=None,
        properties=Properties({asset_id: {"name": "Pump"}}),
        type=None,
    )

    with pytest.raises(ValueError, match="files is missing a source or through"):
        mapper.map_nodes("Asset", {"Asset": [node]})
