from collections import defaultdict
from enum import StrEnum
from typing import Any, TypedDict

from cognite.client.data_classes.data_modeling import (
    Edge,
    EdgeConnection,
    MappedProperty,
    Node,
    NodeList,
    View,
)
from cognite.client.data_classes.data_modeling.data_types import (
    ListablePropertyType,
)
from cognite.client.data_classes.data_modeling.instances import PropertyValue
from cognite.client.data_classes.data_modeling.views import (
    MultiReverseDirectRelation,
    SingleReverseDirectRelation,
)

from industrial_model.constants import EDGE_DIRECTION, EDGE_MARKER, NESTED_SEP
from industrial_model.models import EdgeContainer

from .view_mapper import ViewMapper


class ConnectionTypeEnum(StrEnum):
    DIRECT_RELATION = "DirectRelation"
    REVERSE_DIRECT_RELATION = "ReverseDirectRelation"
    EDGE = "Edge"


class _PropertyMapping(TypedDict):
    is_list: bool
    connection_type: ConnectionTypeEnum
    nodes: dict[tuple[str, str], list[Node]]
    edges: dict[tuple[str, str], list[Edge]]


class QueryResultMapper:
    def __init__(self, view_mapper: ViewMapper):
        self._view_mapper = view_mapper

    def map_nodes(
        self, root_node: str, query_result: dict[str, list[Node | Edge]]
    ) -> list[dict[str, Any]]:
        if root_node not in query_result:
            raise ValueError(f"{root_node} is not available in the query result")

        root_view = self._view_mapper.get_view(root_node)

        values = self._map_node_property(root_node, root_view, query_result)
        if not values:
            return []

        data = [node for nodes in values.values() for node in self.nodes_to_dict(nodes)]

        return data

    def nodes_to_dict(self, nodes: list[Node] | NodeList[Node]) -> list[dict[str, Any]]:
        return [self._node_to_dict(node) for node in nodes]

    def _map_node_property(
        self,
        key: str,
        view: View,
        query_result: dict[str, list[Node | Edge]],
        result_property_key: str | None = None,
    ) -> dict[tuple[str, str], list[Node]] | None:
        if key not in query_result:
            return None

        mappings = self._get_property_mappings(key, view, query_result)

        view_id = view.as_id()

        def get_node_id(node: Node) -> tuple[str, str]:
            if not result_property_key:
                return (node.space, node.external_id)

            entry = properties.get(result_property_key)
            if not isinstance(entry, dict):
                raise ValueError(f"Invalid result property key {result_property_key}")

            return entry.get("space", ""), entry.get("externalId", "")

        visited: set[tuple[str, str]] = set()
        result: defaultdict[tuple[str, str], list[Node]] = defaultdict(list)
        for node in query_result[key]:
            identify = (node.space, node.external_id)
            if not isinstance(node, Node) or identify in visited:
                continue

            visited.add(identify)
            properties = node.properties.get(view_id, {})
            if len(properties) == 0:
                continue

            edges_mapping: dict[str, list[EdgeContainer]] = {}
            node_id = get_node_id(node)
            for mapping_key, mapping_value in mappings.items():
                element = properties.get(mapping_key)

                mapping_nodes = mapping_value.get("nodes", {})
                mapping_edges = mapping_value.get("edges", {})
                is_list = mapping_value.get("is_list", False)
                connection_type = mapping_value.get(
                    "connection_type",
                    ConnectionTypeEnum.DIRECT_RELATION,
                )

                if (
                    element is None
                    and connection_type == ConnectionTypeEnum.DIRECT_RELATION
                ):
                    continue

                element_keys = self._get_element_keys(node, element)

                node_entries = [
                    item
                    for element_key in element_keys
                    for item in mapping_nodes.get(element_key, [])
                ]
                if not node_entries:
                    if mapping_key in properties:
                        properties.pop(mapping_key)
                    continue

                entry_data = self.nodes_to_dict(node_entries)
                properties[mapping_key] = entry_data if is_list else entry_data[0]
                edge_entries = [
                    item
                    for element_key in element_keys
                    for item in mapping_edges.get(element_key, [])
                ]
                if edge_entries:
                    edges_mapping[mapping_key] = self._edges_to_model(edge_entries)
            properties["_edges"] = edges_mapping

            node.properties[view_id] = properties

            result[node_id].append(node)

        return dict(result)

    def _get_element_keys(
        self, node: Node, element: PropertyValue | None
    ) -> list[tuple[str, str]]:
        if isinstance(element, dict):
            return [(element.get("space", ""), element.get("externalId", ""))]

        if isinstance(element, list):
            return [
                (item.get("space", ""), item.get("externalId", ""))
                for item in element
                if isinstance(item, dict)
            ]

        return [(node.space, node.external_id)]

    def _get_property_mappings(
        self,
        key: str,
        view: View,
        query_result: dict[str, list[Node | Edge]],
    ) -> dict[str, _PropertyMapping]:
        mappings: dict[str, _PropertyMapping] = {}

        for property_name, property in view.properties.items():
            property_key = f"{key}{NESTED_SEP}{property_name}"

            nodes: dict[tuple[str, str], list[Node]] | None = None
            edges: dict[tuple[str, str], list[Edge]] | None = None
            is_list = False
            connection_type: ConnectionTypeEnum = ConnectionTypeEnum.DIRECT_RELATION

            if isinstance(property, MappedProperty) and property.source:
                nodes = self._map_node_property(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    query_result,
                )
                is_list = (
                    isinstance(property.type, ListablePropertyType)
                    and property.type.is_list
                )
                connection_type = ConnectionTypeEnum.DIRECT_RELATION
            elif isinstance(property, SingleReverseDirectRelation) and property.source:
                nodes = self._map_node_property(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    query_result,
                    property.through.property,
                )
                is_list = False
                connection_type = ConnectionTypeEnum.REVERSE_DIRECT_RELATION
            elif isinstance(property, MultiReverseDirectRelation) and property.source:
                nodes = self._map_node_property(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    query_result,
                    property.through.property,
                )
                is_list = True
                connection_type = ConnectionTypeEnum.REVERSE_DIRECT_RELATION

            elif isinstance(property, EdgeConnection) and property.source:
                nodes, edges = self._map_edge_property(
                    property_key,
                    self._view_mapper.get_view(property.source.external_id),
                    query_result,
                    property.direction,
                )
                is_list = True
                connection_type = ConnectionTypeEnum.EDGE

            if nodes is not None:
                mappings[property_name] = _PropertyMapping(
                    is_list=is_list,
                    connection_type=connection_type,
                    nodes=nodes,
                    edges=edges or {},
                )

        return mappings

    def _map_edge_property(
        self,
        key: str,
        view: View,
        query_result: dict[str, list[Node | Edge]],
        edge_direction: EDGE_DIRECTION,
    ) -> tuple[
        dict[tuple[str, str], list[Node]] | None,
        dict[tuple[str, str], list[Edge]] | None,
    ]:
        edge_key = f"{key}{NESTED_SEP}{EDGE_MARKER}"
        if key not in query_result or edge_key not in query_result:
            return None, None

        nodes = self._map_node_property(key, view, query_result)
        if not nodes:
            return None, None

        visited: set[tuple[str, str]] = set()
        nodes_result: defaultdict[tuple[str, str], list[Node]] = defaultdict(list)
        edges_result: defaultdict[tuple[str, str], list[Edge]] = defaultdict(list)
        for edge in query_result[edge_key]:
            identify = (edge.space, edge.external_id)
            if not isinstance(edge, Edge) or identify in visited:
                continue

            visited.add(identify)
            entry_key, node_key = (
                (
                    edge.end_node.as_tuple(),
                    edge.start_node.as_tuple(),
                )
                if edge_direction == "inwards"
                else (edge.start_node.as_tuple(), edge.end_node.as_tuple())
            )
            edges_result[entry_key].append(edge)
            if node_item := nodes.get(node_key):
                nodes_result[entry_key].extend(node_item)

        return dict(nodes_result), dict(edges_result)

    def _edges_to_model(self, edges: list[Edge]) -> list[EdgeContainer]:
        return [EdgeContainer.model_validate(edge) for edge in edges]

    def _node_to_dict(self, node: Node) -> dict[str, Any]:
        entry = node.dump()
        properties: dict[str, dict[str, dict[str, Any]]] = entry.pop("properties") or {}
        for space_mapping in properties.values():
            for view_mapping in space_mapping.values():
                entry.update(view_mapping)

        return entry
