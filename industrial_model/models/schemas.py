from collections import defaultdict
from functools import lru_cache
from typing import (
    Any,
    TypeVar,
)

from pydantic import BaseModel

from industrial_model.constants import EDGE_MARKER, NESTED_SEP, RelationMode

TBaseModel = TypeVar("TBaseModel", bound=BaseModel)


def get_schema_properties(
    cls: type[TBaseModel],
    nested_separator: str,
    prefix: str | None = None,
    relation_modes: dict[str, RelationMode] | None = None,
) -> list[str]:
    keys = list(_get_schema_property_paths(cls, nested_separator))

    if relation_modes:
        keys = _filter_relation_mode_keys(keys, nested_separator, relation_modes)

    if not prefix:
        return keys

    return [f"{prefix + nested_separator}{key}" for key in keys]


def _filter_relation_mode_keys(
    keys: list[str],
    nested_separator: str,
    relation_modes: dict[str, RelationMode],
) -> list[str]:
    removal_prefix_keys: list[str] = []
    keep_keys: set[str] = set()
    for relation_mode_key, relation_mode in relation_modes.items():
        if relation_mode != "instanceId":
            continue
        entry = relation_mode_key + nested_separator
        removal_prefix_keys.append(entry)
        keep_keys.add(entry + "externalId")
        keep_keys.add(entry + "space")

    if not removal_prefix_keys:
        return keys

    removal_prefixes = tuple(removal_prefix_keys)
    return [
        key for key in keys if not key.startswith(removal_prefixes) or key in keep_keys
    ]


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


@lru_cache(maxsize=256)
def _get_schema_property_paths(
    cls: type[BaseModel], nested_separator: str
) -> tuple[str, ...]:
    schema = cls.model_json_schema(by_alias=True)
    data = _get_schema_type_properties(schema, schema) or {}
    return tuple(_flatten_dict_keys(data, None, nested_separator))


def _get_schema_type_properties(
    root_schema: dict[str, Any],
    schema: dict[str, Any],
    parent_ref: str | None = None,
    visited_count: defaultdict[str, int] | None = None,
    ref_path: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    current_ref = schema.get("title")
    if "$ref" in schema:
        resolved_ref, resolved_schema = _resolve_schema_ref(root_schema, schema["$ref"])
        if resolved_ref is None or resolved_schema is None:
            return None
        current_ref = resolved_ref
        schema = resolved_schema

        if visited_count is not None:
            if visited_count[current_ref] > 1:
                return None
            if current_ref in ref_path and parent_ref != current_ref:
                return _get_schema_shallow_properties(schema)
            if parent_ref == current_ref:
                visited_count[current_ref] += 1
        if parent_ref is not None:
            ref_path = (*ref_path, current_ref)

    return {
        key: _get_schema_field_properties(
            root_schema,
            field_schema,
            current_ref,
            visited_count or defaultdict(lambda: 0),
            ref_path,
        )
        for key, field_schema in schema.get("properties", {}).items()
    }


def _get_schema_shallow_properties(schema: dict[str, Any]) -> dict[str, Any]:
    return dict.fromkeys(schema.get("properties", {}))


def _get_schema_field_properties(
    root_schema: dict[str, Any],
    schema: dict[str, Any],
    parent_ref: str | None,
    visited_count: defaultdict[str, int],
    ref_path: tuple[str, ...],
) -> dict[str, Any] | None:
    if "$ref" in schema:
        return _get_schema_type_properties(
            root_schema, schema, parent_ref, visited_count, ref_path
        )

    items = schema.get("items")
    if isinstance(items, dict):
        return _get_schema_field_properties(
            root_schema, items, parent_ref, visited_count, ref_path
        )

    properties: dict[str, Any] = {}
    for union_key in ("anyOf", "oneOf", "allOf"):
        for option_schema in schema.get(union_key, []):
            option_properties = _get_schema_field_properties(
                root_schema, option_schema, parent_ref, visited_count, ref_path
            )
            _merge_relation_properties(properties, option_properties)

    return properties or None


def _resolve_schema_ref(
    root_schema: dict[str, Any], ref: str
) -> tuple[str | None, dict[str, Any] | None]:
    defs_prefix = "#/$defs/"
    if not ref.startswith(defs_prefix):
        return None, None

    ref_name = _decode_json_pointer_token(ref.removeprefix(defs_prefix))
    schema = root_schema.get("$defs", {}).get(ref_name)
    return ref_name, schema if isinstance(schema, dict) else None


def _decode_json_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _merge_relation_properties(
    target: dict[str, Any], source: dict[str, Any] | None
) -> None:
    if not source:
        return

    for key, value in source.items():
        if key not in target:
            target[key] = value
            continue

        target_value = target[key]
        if isinstance(target_value, dict) and isinstance(value, dict):
            _merge_relation_properties(target_value, value)
        elif isinstance(value, dict):
            target[key] = value


def _flatten_dict_keys(
    data: dict[str, Any], parent_key: str | None, nested_separator: str
) -> list[str]:
    paths: set[str] = set()
    _collect_flattened_dict_keys(data, parent_key, nested_separator, paths)
    return sorted(paths)


def _collect_flattened_dict_keys(
    data: dict[str, Any],
    parent_key: str | None,
    nested_separator: str,
    paths: set[str],
) -> None:
    for key, value in data.items():
        full_key = f"{parent_key}{nested_separator}{key}" if parent_key else key
        paths.add(full_key)
        if isinstance(value, dict) and value:
            _collect_flattened_dict_keys(value, full_key, nested_separator, paths)
        elif isinstance(value, str):
            paths.add(f"{full_key}{nested_separator}{value}")
        elif isinstance(value, list | set):
            paths.update(f"{full_key}{nested_separator}{item}" for item in value)
