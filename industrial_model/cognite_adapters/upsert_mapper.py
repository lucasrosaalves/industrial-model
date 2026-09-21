import datetime
from typing import Any

from cognite.client.data_classes.data_modeling import (
    DirectRelationReference,
    EdgeApply,
    NodeApply,
    NodeOrEdgeData,
)

from industrial_model.cognite_adapters.models import UpsertOperation
from industrial_model.models import (
    EdgeContainer,
    IngestionMode,
    InstanceId,
    TWritableViewInstance,
)
from industrial_model.utils import datetime_to_ms_iso_timestamp

from .view_mapper import ViewMapper
from .view_schema import ViewProperty


class UpsertMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper

    def map(
        self,
        instances: list[TWritableViewInstance],
        remove_unset: bool,
        ingestion_mode: IngestionMode = "upsert",
    ) -> UpsertOperation:
        nodes: dict[tuple[str, str], NodeApply] = {}
        edges: dict[tuple[str, str], EdgeApply] = {}
        edges_to_delete: dict[tuple[str, str], EdgeContainer] = {}

        for instance in instances:
            entry_nodes, entry_edges, entry_edges_to_delete = self._map_instance(
                instance, remove_unset, ingestion_mode
            )

            nodes[instance.as_tuple()] = entry_nodes
            edges.update({(item.space, item.external_id): item for item in entry_edges})
            edges_to_delete.update(
                {(item.space, item.external_id): item for item in entry_edges_to_delete}
            )

        return UpsertOperation(
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            edges_to_delete=list(edges_to_delete.values()),
        )

    def _map_instance(
        self,
        instance: TWritableViewInstance,
        remove_unset: bool,
        ingestion_mode: IngestionMode,
    ) -> tuple[NodeApply, list[EdgeApply], list[EdgeContainer]]:
        view = self._view_mapper.get_view(instance.get_view_external_id())

        edges: list[EdgeApply] = []
        edges_to_delete: list[EdgeContainer] = []
        properties: dict[str, Any] = {}
        for property_name, property in view.properties.items():
            property_key = instance.get_field_name(property_name)
            if not property_key:
                continue

            if remove_unset and property_key not in instance.model_fields_set:
                continue

            entry = instance.__getattribute__(property_key)

            if property.kind == "mapped":
                properties[property_name] = self._get_mapped_property_value(entry)
            elif property.kind == "edge" and isinstance(entry, list):
                possible_entries = self._map_edges(
                    instance, property, property_key, entry
                )

                previous_edges = {
                    item.as_tuple(): item
                    for item in instance._edges.get(property_name, [])
                }

                new_entries = [
                    edge
                    for edge_id, edge in possible_entries.items()
                    if edge_id not in previous_edges
                ]
                edges_to_delete.extend(
                    [
                        previous_edges[edge_id]
                        for edge_id in previous_edges
                        if edge_id not in possible_entries
                    ]
                )

                edges.extend(new_entries)

        node = NodeApply(
            external_id=instance.external_id,
            space=instance.space,
            existing_version=self._existing_version(ingestion_mode),
            sources=[NodeOrEdgeData(source=view.as_id(), properties=properties)],
        )

        return node, edges, edges_to_delete

    def _get_mapped_property_value(self, entry: Any) -> Any:
        if isinstance(entry, list):
            return [self._get_mapped_property_value(item) for item in entry]

        if isinstance(entry, InstanceId):
            return DirectRelationReference(
                space=entry.space, external_id=entry.external_id
            )
        if isinstance(entry, datetime.datetime):
            return datetime_to_ms_iso_timestamp(entry)
        if isinstance(entry, datetime.date):
            return entry.strftime("%Y-%m-%d")
        return entry

    def _map_edges(
        self,
        instance: TWritableViewInstance,
        property: ViewProperty,
        property_name: str,
        values: list[Any],
    ) -> dict[tuple[str, str], EdgeApply]:
        if property.edge_type is None:
            raise ValueError(f"Edge property {property_name} is missing a type")
        edge_type = InstanceId.model_validate(property.edge_type)

        result: dict[tuple[str, str], EdgeApply] = {}
        for value in values:
            if not isinstance(value, InstanceId):
                raise ValueError(
                    f"Invalid value for edge property {property_name}: "
                    f"Received {type(value)} | Expected: InstanceId"
                )

            start_node, end_node = (
                (instance, value)
                if property.direction == "outwards"
                else (value, instance)
            )

            edge_id = instance.edge_id_factory(value, edge_type)

            result[edge_id.as_tuple()] = EdgeApply(
                external_id=edge_id.external_id,
                space=edge_id.space,
                type=property.edge_type,
                start_node=start_node.as_tuple(),
                end_node=end_node.as_tuple(),
            )

        return result

    @staticmethod
    def _existing_version(ingestion_mode: IngestionMode) -> int | None:
        return 0 if ingestion_mode == "create" else None
