from typing import Any, TypeVar

from .entities import InstanceId, ViewInstance

TEntity = TypeVar("TEntity", bound=ViewInstance)


class RelationNotIncludedError(TypeError):
    """Raised when a relation is still an ``InstanceId`` instead of the entity type.

    This usually means the query did not pass the relation in ``include``.
    """

    def __init__(
        self,
        message: str,
        *,
        field_name: str,
        expected_type: type[Any],
        actual: Any,
    ) -> None:
        super().__init__(message)
        self.field_name = field_name
        self.expected_type = expected_type
        self.actual = actual


def relation_or_none(value: Any, entity_type: type[TEntity]) -> TEntity | None:
    if isinstance(value, list):
        raise TypeError("value is a list relation; use relations_or_none() instead")
    return value if isinstance(value, entity_type) else None


def require_relation(
    value: Any,
    entity_type: type[TEntity],
    *,
    field_name: str,
    owner: InstanceId,
) -> TEntity:
    if isinstance(value, list):
        raise TypeError("value is a list relation; use require_relations() instead")
    if isinstance(value, entity_type):
        return value
    raise _relation_not_included_error(owner, field_name, entity_type, value)


def relations_or_none(value: Any, entity_type: type[TEntity]) -> list[TEntity]:
    if not isinstance(value, list):
        raise TypeError("value is not a list relation; use relation_or_none() instead")
    return [item for item in value if isinstance(item, entity_type)]


def require_relations(
    value: Any,
    entity_type: type[TEntity],
    *,
    field_name: str,
    owner: InstanceId,
) -> list[TEntity]:
    if not isinstance(value, list):
        raise TypeError("value is not a list relation; use require_relation() instead")
    entities: list[TEntity] = []
    for item in value:
        if not isinstance(item, entity_type):
            raise _relation_not_included_error(owner, field_name, entity_type, value)
        entities.append(item)
    return entities


def _relation_not_included_error(
    owner: InstanceId,
    field_name: str,
    expected_type: type[Any],
    actual: Any,
) -> RelationNotIncludedError:
    owner_label = f"{type(owner).__name__}({owner.space!r}, {owner.external_id!r})"
    expected = expected_type.__name__
    return RelationNotIncludedError(
        f"Relation {field_name!r} on {owner_label} "
        f"{_describe_unloaded_relation(actual, expected, field_name)}.",
        field_name=field_name,
        expected_type=expected_type,
        actual=actual,
    )


def _describe_unloaded_relation(actual: Any, expected: str, display_name: str) -> str:
    include_hint = f'Query with include=["{display_name}"] to load the related entity'
    if actual is None:
        return "is unset"
    if isinstance(actual, list):
        unloaded = [item for item in actual if type(item) is InstanceId]
        if unloaded:
            sample = ", ".join(
                f"InstanceId({item.space!r}, {item.external_id!r})"
                for item in unloaded[:3]
            )
            extra = f", {len(unloaded) - 3} more" if len(unloaded) > 3 else ""
            return (
                f"contains {len(unloaded)} InstanceId value(s) that are not "
                f"{expected}: {sample}{extra}. {include_hint}"
            )
        types = sorted({type(item).__name__ for item in actual})
        return f"contains values that are not {expected} (found {', '.join(types)})"
    if type(actual) is InstanceId:
        return (
            f"is InstanceId({actual.space!r}, {actual.external_id!r}), "
            f"not {expected}. {include_hint}"
        )
    return f"has type {type(actual).__name__}, expected {expected}"
