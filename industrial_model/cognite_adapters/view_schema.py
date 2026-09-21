from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from cognite.client.data_classes.data_modeling import (
    EdgeConnection,
    MappedProperty,
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.data_types import (
    DirectRelationReference,
    ListablePropertyType,
)
from cognite.client.data_classes.data_modeling.views import (
    MultiReverseDirectRelation,
    SingleReverseDirectRelation,
)

logger = logging.getLogger(__name__)

EdgeDirection = Literal["outwards", "inwards"]
PropertyKind = Literal["mapped", "reverse", "edge"]


@dataclass(frozen=True, slots=True)
class ViewProperty:
    kind: PropertyKind
    source: ViewId | None = None
    is_list: bool = False
    through: str | None = None
    edge_type: DirectRelationReference | None = None
    direction: EdgeDirection = "outwards"

    def as_source(self) -> str:
        args = [repr(self.kind)]
        if self.source is not None:
            args.append(f"source={_view_id_source(self.source)}")
        if self.is_list:
            args.append("is_list=True")
        if self.through is not None:
            args.append(f"through={self.through!r}")
        if self.edge_type is not None:
            args.append(
                f"edge_type={_direct_relation_reference_source(self.edge_type)}"
            )
        if self.direction != "outwards":
            args.append(f"direction={self.direction!r}")
        return f"ViewProperty({', '.join(args)})"

    def __repr__(self) -> str:
        return self.as_source()


@dataclass(frozen=True, slots=True)
class ViewSchema:
    space: str
    external_id: str
    version: str
    properties: dict[str, ViewProperty]

    def as_id(self) -> ViewId:
        return ViewId(self.space, self.external_id, self.version)

    def as_property_ref(self, property: str) -> tuple[str, str, str]:
        return (self.space, f"{self.external_id}/{self.version}", property)

    def as_source(self) -> str:
        props = ", ".join(
            f"{name!r}: {prop.as_source()}" for name, prop in self.properties.items()
        )
        return (
            f"ViewSchema(space={self.space!r}, "
            f"external_id={self.external_id!r}, "
            f"version={self.version!r}, "
            f"properties={{{props}}})"
        )

    @classmethod
    def from_cognite(cls, view: View) -> ViewSchema:
        properties: dict[str, ViewProperty] = {}
        for name, prop in view.properties.items():
            converted = _property_from_cognite(prop)
            if converted is None:
                logger.warning(
                    "Skipping unsupported property %r on view %s/%s/%s (%s)",
                    name,
                    view.space,
                    view.external_id,
                    view.version,
                    type(prop).__name__,
                )
                continue
            properties[name] = converted
        return cls(view.space, view.external_id, view.version, properties)

    def __repr__(self) -> str:
        return self.as_source()


def render_view_schemas(views: Sequence[ViewSchema]) -> str:
    return f"[{', '.join(view.as_source() for view in views)}]"


def _view_id_source(view_id: ViewId) -> str:
    return (
        f"ViewId(space={view_id.space!r}, "
        f"external_id={view_id.external_id!r}, "
        f"version={view_id.version!r})"
    )


def _direct_relation_reference_source(ref: DirectRelationReference) -> str:
    return (
        f"DirectRelationReference(space={ref.space!r}, external_id={ref.external_id!r})"
    )


def _property_from_cognite(property_: object) -> ViewProperty | None:
    if isinstance(property_, MappedProperty):
        return ViewProperty(
            kind="mapped",
            source=property_.source,
            is_list=(
                isinstance(property_.type, ListablePropertyType)
                and property_.type.is_list
            ),
        )
    if isinstance(property_, (SingleReverseDirectRelation, MultiReverseDirectRelation)):
        return ViewProperty(
            kind="reverse",
            source=property_.source,
            through=property_.through.property,
            is_list=isinstance(property_, MultiReverseDirectRelation),
        )
    if isinstance(property_, EdgeConnection):
        return ViewProperty(
            kind="edge",
            source=property_.source,
            edge_type=property_.type,
            direction=property_.direction,
        )
    return None
