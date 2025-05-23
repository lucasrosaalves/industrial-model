from abc import abstractmethod
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    TypedDict,
    TypeVar,
)

from pydantic import PrivateAttr

from .base import DBModelMetaclass, RootModel


class InstanceId(RootModel):
    external_id: str
    space: str

    def __hash__(self) -> int:
        return hash((self.external_id, self.space))

    def __eq__(self, other: Any) -> bool:
        return (
            other is not None
            and isinstance(other, InstanceId)
            and self.external_id == other.external_id
            and self.space == other.space
        )

    def as_tuple(self) -> tuple[str, str]:
        return (self.space, self.external_id)


class EdgeContainer(InstanceId):
    type: InstanceId
    start_node: InstanceId
    end_node: InstanceId


TInstanceId = TypeVar("TInstanceId", bound=InstanceId)


class ViewInstanceConfig(TypedDict, total=False):
    view_external_id: str | None
    instance_spaces: list[str] | None
    instance_spaces_prefix: str | None


class ViewInstance(InstanceId, metaclass=DBModelMetaclass):
    view_config: ClassVar[ViewInstanceConfig] = ViewInstanceConfig()

    _edges: dict[str, list[EdgeContainer]] = PrivateAttr(default_factory=dict)

    @classmethod
    def get_view_external_id(cls) -> str:
        return cls.view_config.get("view_external_id") or cls.__name__

    def get_field_name(self, field_name_or_alias: str) -> str | None:
        entry = self.__class__.model_fields.get(field_name_or_alias)
        if entry:
            return field_name_or_alias

        for key, field_info in self.__class__.model_fields.items():
            if field_info.alias == field_name_or_alias:
                return key

        return None


class WritableViewInstance(ViewInstance):
    @abstractmethod
    def edge_id_factory(
        self, target_node: TInstanceId, edge_type: InstanceId
    ) -> InstanceId:
        raise NotImplementedError(
            "edge_id_factory method must be implemented in subclasses"
        )


TViewInstance = TypeVar("TViewInstance", bound=ViewInstance)
TWritableViewInstance = TypeVar(
    "TWritableViewInstance", bound=WritableViewInstance
)


class PaginatedResult(RootModel, Generic[TViewInstance]):
    data: list[TViewInstance]
    has_next_page: bool
    next_cursor: str | None


class AggregationResult(RootModel):
    group: dict[str, str | int | float | bool | InstanceId] | None
    value: float
    aggregate: str


ValidationMode = Literal["raiseOnError", "ignoreOnError"]
