from industrial_model import (
    AggregatedViewInstance,
    ViewInstanceConfig,
    aggregate,
)

from .hubs import generate_engine

if __name__ == "__main__":
    adapter = generate_engine()

    default_config = ViewInstanceConfig(view_external_id="OEEEvent")

    class AggregatedEvent(AggregatedViewInstance):
        view_config = default_config
        event_definition: str

    aggregate_result = adapter.aggregate(aggregate(AggregatedEvent, "count"))
    print(aggregate_result)
