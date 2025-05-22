from typing import Literal

from cognite.client.data_classes.data_modeling import (
    Edge,
    Node,
    NodeListWithCursor,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.query import (
    Query as CogniteQuery,
)
from cognite.client.data_classes.data_modeling.query import (
    QueryResult as CogniteQueryResult,
)
from cognite.client.data_classes.data_modeling.query import (
    ResultSetExpression,
)
from cognite.client.data_classes.data_modeling.query import (
    Select as CogniteSelect,
)

from industrial_model.constants import MAX_LIMIT
from industrial_model.models import (
    TViewInstance,
    get_parent_and_children_nodes,
)

NODE_PROPERTIES = {"externalId", "space", "createdTime", "deletedTime"}
INTANCE_TYPE = Literal["node", "edge"]


def get_property_ref(
    property: str, view: View | ViewId, instance_type: INTANCE_TYPE = "node"
) -> tuple[str, str, str] | tuple[str, str]:
    return (
        view.as_property_ref(property)
        if property not in NODE_PROPERTIES
        else (instance_type, property)
    )


def get_cognite_instance_ids(
    instance_ids: list[TViewInstance],
) -> list[dict[str, str]]:
    return [
        get_cognite_instance_id(instance_id) for instance_id in instance_ids
    ]


def get_cognite_instance_id(instance_id: TViewInstance) -> dict[str, str]:
    return {"space": instance_id.space, "externalId": instance_id.external_id}


def get_query_for_dependencies_pagination(
    query: CogniteQuery,
    query_result: CogniteQueryResult,
    view_external_id: str,
) -> CogniteQuery | None:
    nodes_parent, nodes_children = get_parent_and_children_nodes(
        set(query_result.cursors.keys())
    )

    leaf_cursors = _get_leaf_cursors(
        query_result, view_external_id, nodes_parent, nodes_children
    )

    if not leaf_cursors:
        return None

    return _create_query(query, nodes_parent, nodes_children, leaf_cursors)


def map_nodes_and_edges(
    query_result: CogniteQueryResult, query: CogniteQuery
) -> dict[str, list[Node | Edge]]:
    result_schema = query.instance_type_by_result_expression()

    return {
        key: query_result.get_nodes(key).data
        if entity_type is NodeListWithCursor
        else query_result.get_edges(key).data
        for key, entity_type in result_schema.items()
        if entity_type is not None
    }


def append_nodes_and_edges(
    initial_dataset: dict[str, list[Node | Edge]],
    additional_dataset: dict[str, list[Node | Edge]] | None,
) -> dict[str, list[Node | Edge]]:
    if not additional_dataset:
        return initial_dataset
    for key, additional_data in additional_dataset.items():
        if key not in initial_dataset:
            initial_dataset[key] = []
        initial_dataset[key].extend(additional_data)
    return initial_dataset


def _create_query(
    previous_query: CogniteQuery,
    nodes_parent: dict[str, set[str]],
    nodes_children: dict[str, set[str]],
    leaf_cursors: dict[str, str],
) -> CogniteQuery:
    with_: dict[str, ResultSetExpression] = {}
    select_: dict[str, CogniteSelect] = {}
    final_cursors: dict[str, str | None] = {}

    for cursor_key, cursor_value in leaf_cursors.items():
        children = nodes_children[cursor_key]
        parent = nodes_parent[cursor_key]

        valid_keys = parent.union(children)
        valid_keys.add(cursor_key)

        with_.update(
            {k: v for k, v in previous_query.with_.items() if k in valid_keys}
        )
        select_.update(
            {k: v for k, v in previous_query.select.items() if k in valid_keys}
        )

        final_cursors.update(
            {k: v for k, v in previous_query.cursors.items() if k in parent}
        )
        final_cursors[cursor_key] = cursor_value

    return CogniteQuery(with_=with_, select=select_, cursors=final_cursors)


def _get_leaf_cursors(
    query_result: CogniteQueryResult,
    view_external_id: str,
    nodes_parent: dict[str, set[str]],
    nodes_children: dict[str, set[str]],
) -> dict[str, str]:
    target_cursors: dict[str, str] = {}
    for cursor_key, cursor_value in query_result.cursors.items():
        if (
            cursor_key == view_external_id
            or not cursor_value
            or len(query_result[cursor_key]) != MAX_LIMIT
        ):
            continue

        children = nodes_children[cursor_key]

        target_cursors_keys = target_cursors.keys()
        if len(children.intersection(target_cursors_keys)) > 0:
            continue

        parent = nodes_parent[cursor_key]
        cursor_to_remove = parent.intersection(target_cursors_keys)
        for cursor_key_to_remove in cursor_to_remove:
            target_cursors.pop(cursor_key_to_remove)

        target_cursors[cursor_key] = cursor_value
    return target_cursors
