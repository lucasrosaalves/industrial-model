import datetime
import json
from typing import Annotated

from industrial_model.queries.models import BasePaginatedQuery
from industrial_model.queries.params import QueryParam

from .hubs import generate_engine
from .models import Event

if __name__ == "__main__":
    adapter = generate_engine()

    class EventRequest(BasePaginatedQuery):
        start_date_time_gt: Annotated[
            datetime.datetime | None,
            QueryParam(property="startDateTime", operator=">"),
        ] = None
        event_definition_exists: Annotated[
            bool | None, QueryParam(property="eventDefinition", operator="exists")
        ] = None

    filter = EventRequest(
        start_date_time_gt=datetime.datetime(2025, 3, 1),
        event_definition_exists=False,
        limit=1,
    )

    statement = filter.to_statement(Event)

    result = adapter.query(statement)
    print(len(result.data))
    json.dump(result.model_dump(mode="json"), open("events.json", "w"), indent=2)
