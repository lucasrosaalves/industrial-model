import datetime
import json

from industrial_model import col, select

from .hubs import generate_engine
from .models import DescribableEntity, Event

if __name__ == "__main__":
    adapter = generate_engine()

    filter = (
        col(Event.start_date_time).gt_(datetime.datetime(2025, 3, 1))
        & col(Event.ref_site).nested_(
            DescribableEntity.external_id == "STS-CLK"
        )
        & (col(Event.start_date_time) < datetime.datetime(2025, 6, 1))
    )

    statement = select(Event).limit(50).where(filter)

    result = [
        item.model_dump(mode="json")
        for item in adapter.query_all_pages(statement)
    ]
    print(len(result))
    json.dump(result, open("entities.json", "w"), indent=2)
