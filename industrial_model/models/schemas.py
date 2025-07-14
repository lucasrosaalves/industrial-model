import inspect
from collections import defaultdict
from types import UnionType
from typing import (
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel

from industrial_model.constants import EDGE_MARKER, NESTED_SEP

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


def get_schema_properties(
    cls: type[TBaseModel],
    nested_separator: str,
    prefix: str | None = None,
) -> list[str]:
    data = _get_type_properties(cls) or {}
    keys = _flatten_dict_keys(data, None, nested_separator)
    if not prefix:
        return keys

    return [f"{prefix}{nested_separator}{key}" for key in keys]


def get_parent_and_children_nodes(
    keys: set[str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    nodes_parent: dict[str, set[str]] = {}
    nodes_children: defaultdict[str, set[str]] = defaultdict(set)
    for key in keys:
        key_parts = key.split(NESTED_SEP)
        parent_paths = {
            NESTED_SEP.join(key_parts[:i]) for i in range(len(key_parts) - 1, 0, -1)
        }

        valid_paths: set[str] = set()
        for parent_path in parent_paths:
            parent_path_edge_marker = parent_path + NESTED_SEP + EDGE_MARKER
            if parent_path_edge_marker in keys:
                valid_paths.add(parent_path_edge_marker)
                nodes_children[parent_path_edge_marker].add(key)
            if parent_path in keys:
                valid_paths.add(parent_path)
                nodes_children[parent_path].add(key)

        nodes_parent[key] = valid_paths
    return nodes_parent, dict(nodes_children)


def _get_type_properties(
    cls: type[BaseModel],
    parent_type: type[BaseModel] | None = None,
    visited_count: defaultdict[type, int] | None = None,
) -> dict[str, Any] | None:
    if visited_count is not None:
        if visited_count[cls] > 1:
            return None
        elif parent_type == cls:
            visited_count[cls] += 1

    hints = get_type_hints(cls)
    origins = {
        key: _get_field_type(
            type_hint,
            cls,
            visited_count or defaultdict(lambda: 0),
        )
        for key, type_hint in hints.items()
    }

    return {
        field_info.alias or key: origins[key][1]
        for key, field_info in cls.model_fields.items()
        if key in origins
    }


def _get_field_type(
    type_hint: type,
    parent_type: type[BaseModel],
    visited_count: defaultdict[type, int],
) -> tuple[bool, dict[str, Any] | None]:
    should_iter = _type_is_list_or_union(type_hint)

    if not should_iter:
        return _get_field_relations(
            [_cast_base_model(type_hint)], parent_type, visited_count
        )

    entries: list[type[BaseModel] | None] = []
    for arg in get_args(type_hint):
        if _type_is_list_or_union(arg):
            return _get_field_type(arg, parent_type, visited_count)
        entries.append(_cast_base_model(arg))

    return _get_field_relations(entries, parent_type, visited_count)


def _get_field_relations(
    entries: list[type[TBaseModel] | None],
    parent_type: type[BaseModel],
    visited_count: defaultdict[type, int],
) -> tuple[bool, dict[str, Any] | None]:
    entry_type = next((type_ for type_ in entries if type_ is not None), None)

    if not entry_type:
        return False, None

    properties = _get_type_properties(entry_type, parent_type, visited_count)

    return True, properties


def _type_is_list_or_union(entry: type) -> bool:
    origin = get_origin(entry)
    is_union = origin in (Union, UnionType)
    is_list = origin in (list, list)

    return is_union or is_list


def _cast_base_model(entry: type) -> type[TBaseModel] | None:
    is_base_model = (
        entry is not type(None)
        and inspect.isclass(entry) is True
        and issubclass(entry, BaseModel)
    )
    return entry if is_base_model else None


def _flatten_dict_keys(
    data: dict[str, Any], parent_key: str | None, nested_separator: str
) -> list[str]:
    paths: set[str] = set()
    for key, value in data.items():
        full_key = f"{parent_key}{nested_separator}{key}" if parent_key else key
        paths.add(full_key)
        if isinstance(value, dict) and value:
            paths.update(_flatten_dict_keys(value, full_key, nested_separator))
        elif isinstance(value, str):
            paths.add(f"{full_key}{nested_separator}{value}")
        elif isinstance(value, list | set):
            paths.update([f"{full_key}{nested_separator}{item}" for item in value])

    return sorted(paths)
