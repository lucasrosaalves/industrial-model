from typing import Any

from .entities import EdgeContainer, TViewInstance, ViewInstance


def include_edges(
    root_item: dict[str, Any], validated_root_item: TViewInstance
) -> None:
    if not isinstance(root_item, dict) or not isinstance(
        validated_root_item, ViewInstance
    ):
        return

    for property_, value in root_item.items():
        field_key = validated_root_item.get_field_name(property_)
        if not field_key:
            continue
        _handle_edge_property(validated_root_item, value, field_key)
    _include_edges(root_item, validated_root_item)


def _handle_edge_property(
    validated_root_item: TViewInstance, value: Any, field_key: str
) -> None:
    attr_value = getattr(validated_root_item, field_key, None)

    if isinstance(value, dict):
        _handle_dict_property(value, attr_value)
        return

    if (
        not isinstance(value, list)
        or not isinstance(attr_value, list)
        or len(value) != len(attr_value)
    ):
        return

    for index, value_item in enumerate(value):
        entry = attr_value[index]
        _handle_dict_property(value_item, entry)


def _handle_dict_property(value: Any, attr_value: Any) -> None:
    if isinstance(value, dict) and isinstance(attr_value, ViewInstance):
        include_edges(value, attr_value)


def _include_edges(item: dict[str, Any], validated_item: TViewInstance) -> None:
    if "_edges" not in item or not isinstance(item["_edges"], dict):
        return
    entries: dict[str, list[EdgeContainer]] = {}
    for property_, edges in item["_edges"].items():
        if not edges or not isinstance(edges, list):
            continue

        assert isinstance(edges[0], EdgeContainer)
        entries[property_] = edges
    validated_item._edges = entries
