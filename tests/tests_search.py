import datetime
import json

from industrial_model import col, search

from .hubs import generate_engine
from .models import Event, SearchEvent

if __name__ == "__main__":
    adapter = generate_engine()

    filter = col(SearchEvent.start_date_time).gt_(datetime.datetime(2025, 3, 1)) & (
        col(SearchEvent.start_date_time) < datetime.datetime(2025, 6, 1)
    )

    statement = (
        search(SearchEvent)
        .limit(-1)
        .where(filter)
        .desc(Event.start_date_time)
        .query_by("not runn", [SearchEvent.event_definition])
    )

    items = adapter.search(statement)

    result = [item.model_dump(mode="json") for item in items]
    print(len(result))
    json.dump(result, open("search.json", "w"), indent=2)
