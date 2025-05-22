import json

from industrial_model.cognite_adapters.upsert_mapper import UpsertMapper
from industrial_model.statements import select
from tests.hubs import generate_engine
from tests.models import EventDetail, WritableEvent

if __name__ == "__main__":
    engine = generate_engine()

    view_mapper = engine._cognite_adapter._query_mapper._view_mapper

    upsert_mapper = UpsertMapper(view_mapper)

    statement = select(WritableEvent).limit(1)

    item = engine.query(statement).data[0]

    item.ref_oee_event_detail.clear()
    item.ref_oee_event_detail.append(
        EventDetail(external_id="test", space="test")
    )

    operation = upsert_mapper.map([item])

    data = {
        "nodes": [node.dump() for node in operation.nodes],
        "edges": [edge.dump() for edge in operation.edges],
        "edges_to_delete": [
            edge_to_delete.model_dump(mode="json")
            for edge_to_delete in operation.edges_to_delete
        ],
    }

    json.dump(
        data,
        open("upsert.json", "w"),
        indent=4,
    )
