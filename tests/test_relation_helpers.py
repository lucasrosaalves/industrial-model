import pytest
from pydantic import Field

from industrial_model import InstanceId, RelationNotIncludedError, ViewInstance
from industrial_model.models.relation_helpers import (
    relation_or_none,
    relations_or_none,
    require_relation,
    require_relations,
)


class _RelatedModel(ViewInstance):
    name: str


class _OwnerModel(ViewInstance):
    related: InstanceId | _RelatedModel | None = None
    related_list: list[InstanceId | _RelatedModel] = Field(default_factory=list)


def test_relation_or_none_returns_included_instance() -> None:
    related = _RelatedModel(external_id="r1", space="test-space", name="Related")
    owner = _OwnerModel(
        external_id="o1",
        space="test-space",
        related=related,
    )

    entity = relation_or_none(owner.related, _RelatedModel)
    assert isinstance(entity, _RelatedModel)
    assert entity == related
    assert (
        require_relation(
            owner.related, _RelatedModel, field_name="related", owner=owner
        ).name
        == "Related"
    )


def test_relation_or_none_returns_none_when_unset_or_unloaded() -> None:
    owner = _OwnerModel(
        external_id="o1",
        space="test-space",
        related=InstanceId(external_id="r1", space="test-space"),
    )

    assert relation_or_none(owner.related, _RelatedModel) is None
    assert relation_or_none(None, _RelatedModel) is None


def test_require_relation_requires_entity() -> None:
    owner = _OwnerModel(
        external_id="o1",
        space="test-space",
        related=InstanceId(external_id="r1", space="test-space"),
    )

    with pytest.raises(RelationNotIncludedError, match=r'include=\["related"\]'):
        require_relation(
            owner.related, _RelatedModel, field_name="related", owner=owner
        )

    with pytest.raises(RelationNotIncludedError, match="is unset"):
        require_relation(None, _RelatedModel, field_name="related", owner=owner)


def test_relations_or_none_filters_instance_ids() -> None:
    related = _RelatedModel(external_id="r1", space="test-space", name="Related")
    values: list[InstanceId | _RelatedModel] = [
        related,
        InstanceId(external_id="r2", space="test-space"),
    ]

    assert relations_or_none(values, _RelatedModel) == [related]
    assert relations_or_none(values, _RelatedModel)[0].name == "Related"


def test_require_relations_requires_all_entities() -> None:
    related = _RelatedModel(external_id="r1", space="test-space", name="Related")
    mixed: list[InstanceId | _RelatedModel] = [
        related,
        InstanceId(external_id="r2", space="test-space"),
    ]
    owner = _OwnerModel(external_id="o1", space="test-space", related_list=mixed)

    with pytest.raises(RelationNotIncludedError, match="InstanceId"):
        require_relations(mixed, _RelatedModel, field_name="related_list", owner=owner)

    assert require_relations(
        [related], _RelatedModel, field_name="related_list", owner=owner
    ) == [related]
    assert (
        require_relations([], _RelatedModel, field_name="related_list", owner=owner)
        == []
    )


def test_relation_or_none_rejects_list_value() -> None:
    related = _RelatedModel(external_id="r1", space="test-space", name="Related")
    owner = _OwnerModel(external_id="o1", space="test-space")

    with pytest.raises(TypeError, match="list relation"):
        relation_or_none([related], _RelatedModel)
    with pytest.raises(TypeError, match="not a list relation"):
        relations_or_none(owner.related, _RelatedModel)
