from abc import abstractmethod
from datetime import UTC, date, datetime
from typing import (
    Any,
    ClassVar,
    Generic,
    Literal,
    TypedDict,
    TypeVar,
)

from pydantic import PrivateAttr, computed_field

from industrial_model.statements import Column

from .base import DBModelMetaclass, RootModel


class InstanceId(RootModel, metaclass=DBModelMetaclass):
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
    last_updated_time: int
    created_time: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def created_time_as_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.created_time / 1000, tz=UTC)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def last_updated_time_as_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.last_updated_time / 1000, tz=UTC)


TInstanceId = TypeVar("TInstanceId", bound=InstanceId)


class ViewInstanceConfig(TypedDict, total=False):
    view_external_id: str | None
    instance_spaces: list[str] | None
    instance_spaces_prefix: str | None
    view_code: str | None


class ViewInstance(InstanceId):
    view_config: ClassVar[ViewInstanceConfig] = ViewInstanceConfig()

    _edges: dict[str, list[EdgeContainer]] = PrivateAttr(default_factory=dict)

    @classmethod
    def get_view_external_id(cls) -> str:
        return cls.view_config.get("view_external_id") or cls.__name__

    def get_edge_metadata(self, property: Column | str | Any) -> list[EdgeContainer]:
        assert isinstance(property, Column | str), (
            f"Expected property to be Column, or str, got {type(property).__name__}"
        )
        identifier = property.property if isinstance(property, Column) else property

        edge_map_key = self.get_field_alias(identifier) or self.get_field_name(
            identifier
        )
        if not edge_map_key:
            return []
        return self._edges.get(edge_map_key, [])

    def generate_model_id(
        self,
        fields: list[str] | list[Column] | list[Any],
        view_code_as_prefix: bool = True,
        separator: str = "-",
    ) -> str:
        if not fields:
            raise ValueError("Fields list cannot be empty")
        field_values = self._get_field_values(fields)

        view_code = self.view_config.get("view_code")

        result = separator.join(field_values)
        return (
            f"{view_code}{separator}{result}"
            if view_code_as_prefix and view_code
            else result
        )

    def _get_field_values(
        self, fields: list[str] | list[Column] | list[Any]
    ) -> list[str]:
        field_values: list[str] = []
        for field in fields:
            if not isinstance(field, str | Column):
                field_type = type(field).__name__
                raise TypeError(
                    f"Expected field to be a string or Column, got {field_type}"
                )
            field_name = self.get_field_name(
                field.property if isinstance(field, Column) else field
            )
            if field_name is None:
                raise ValueError(f"Field {field} not found in the model")
            field_entry = getattr(self, field_name)

            field_entry_str = ""
            if isinstance(field_entry, str):
                field_entry_str = field_entry
            elif isinstance(field_entry, date | datetime):
                field_entry_str = field_entry.isoformat()
            elif isinstance(field_entry, InstanceId):
                field_entry_str = field_entry.external_id
            else:
                field_entry_str = str(field_entry)
            field_values.append(field_entry_str.replace(" ", ""))
        return field_values


class WritableViewInstance(ViewInstance):
    @abstractmethod
    def edge_id_factory(
        self, target_node: TInstanceId, edge_type: InstanceId
    ) -> InstanceId:
        raise NotImplementedError(
            "edge_id_factory method must be implemented in subclasses"
        )


class AggregatedViewInstance(RootModel, metaclass=DBModelMetaclass):
    view_config: ClassVar[ViewInstanceConfig] = ViewInstanceConfig()

    value: float

    @classmethod
    def get_view_external_id(cls) -> str:
        return cls.view_config.get("view_external_id") or cls.__name__

    @classmethod
    def get_group_by_fields(cls) -> list[str]:
        group_by_fields: set[str] = set()
        for key, field_info in cls.model_fields.items():
            if key == "value":
                continue
            group_by_fields.add(field_info.alias or key)

        return list(group_by_fields)


TViewInstance = TypeVar("TViewInstance", bound=ViewInstance)
TWritableViewInstance = TypeVar("TWritableViewInstance", bound=WritableViewInstance)
TAggregatedViewInstance = TypeVar(
    "TAggregatedViewInstance", bound=AggregatedViewInstance
)


class PaginatedResult(RootModel, Generic[TViewInstance]):
    data: list[TViewInstance]
    has_next_page: bool
    next_cursor: str | None

    def first_or_default(self) -> TViewInstance | None:
        return self.data[0] if self.data else None


ValidationMode = Literal["raiseOnError", "ignoreOnError"]
