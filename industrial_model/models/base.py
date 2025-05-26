from typing import (
    Any,
    dataclass_transform,
)

from pydantic import BaseModel, ConfigDict, Field
from pydantic._internal import _model_construction
from pydantic.alias_generators import to_camel

from industrial_model.statements import Column


@dataclass_transform(kw_only_default=True, field_specifiers=(Field,))
class DBModelMetaclass(_model_construction.ModelMetaclass):
    is_constructing: bool = False

    def __new__(
        mcs,
        cls_name: str,
        bases: tuple[type[Any], ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        mcs.is_constructing = True
        cls = super().__new__(mcs, cls_name, bases, namespace, **kwargs)
        mcs.is_constructing = False
        return cls

    def __getattr__(self, key: str) -> Any:
        if self.is_constructing:
            return super().__getattr__(key)  # type: ignore

        try:
            return super().__getattr__(key)  # type: ignore
        except AttributeError:
            if key in self.model_fields:
                return Column(self.model_fields[key].alias or key)
            raise


class RootModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    def get_field_name(self, field_name_or_alias: str) -> str | None:
        entry = self.__class__.model_fields.get(field_name_or_alias)
        if entry:
            return field_name_or_alias

        for key, field_info in self.__class__.model_fields.items():
            if field_info.alias == field_name_or_alias:
                return key

        return None
