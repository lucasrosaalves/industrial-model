from __future__ import annotations

from cognite.client.data_classes.data_modeling import (
    EdgeConnection,
    MappedProperty,
    View,
)
from cognite.client.data_classes.data_modeling.data_types import ListablePropertyType
from cognite.client.data_classes.data_modeling.views import (
    MultiReverseDirectRelation,
    SingleReverseDirectRelation,
)
from pydantic import BaseModel, Field

from industrial_model.constants import NESTED_SEP

from .config import InstanceSpaceConfig
from .constants import (
    aggregate_group_types,
    mapping_types,
    python_keywords,
    range_types,
)
from .helpers import to_camel, to_pascal, to_snake


class FieldDefinition(BaseModel):
    field_name: str
    field_alias: str | None
    field_type: str
    is_nullable: bool
    is_list: bool
    concrete_type: str | None = None

    def __str__(self) -> str:
        type_ = self.field_type
        field_properties: dict[str, str] = {}

        if self.field_alias:
            field_properties["alias"] = f'"{self.field_alias}"'
        if self.is_list:
            field_properties["default_factory"] = "list"
            if self.concrete_type:
                type_ = f"list[{type_} | {self.concrete_type}]"
            else:
                type_ = f"list[{type_}]"
        else:
            if self.concrete_type:
                type_ += f" | {self.concrete_type}"
            if self.is_nullable:
                field_properties["default"] = "None"
                type_ += " | None"

        result = f"{self.field_name}: {type_}"
        if not field_properties:
            return result

        if len(field_properties) == 1 and "default" in field_properties:
            return f"{result} = None"

        field_properties_str = ", ".join(
            f"{key}={value}" for key, value in field_properties.items()
        )
        return f"{result} = Field({field_properties_str})"

    @property
    def operators(self) -> list[str]:
        if self.field_type == "Any":
            return []
        if self.is_list:
            return ["contains_all", "contains_any"]

        default_operators = ["eq", "in", "exists"]
        if self.field_type in range_types:
            return default_operators + ["gt", "gte", "lt", "lte"]
        if self.field_type == "str":
            return default_operators + ["prefix"]
        return default_operators

    @property
    def filter_type_name(self) -> str | None:
        if self.is_list:
            return {
                "str": "StringListFilter",
                "InstanceId": "InstanceIdListFilter",
            }.get(self.field_type)
        return {
            "str": "StringFilter",
            "int": "IntFilter",
            "float": "FloatFilter",
            "bool": "BoolFilter",
            "InstanceId": "InstanceIdFilter",
            "datetime.datetime": "DatetimeFilter",
            "datetime.date": "DateFilter",
        }.get(self.field_type)


class RelationDefinition(BaseModel):
    field_name: str
    property: str
    target_view_external_id: str
    is_list: bool = False
    target_view_available: bool = True


class ViewDefinition(BaseModel):
    view_external_id: str
    view_name: str
    view_alias: str | None = None
    view_code: str | None = None
    view_module_name: str
    aggregate_fields: list[FieldDefinition] = Field(default_factory=list)
    search_fields: list[FieldDefinition] = Field(default_factory=list)
    regular_fields: list[FieldDefinition] = Field(default_factory=list)
    relation_fields: list[RelationDefinition] = Field(default_factory=list)
    all_relation_paths: list[str] = Field(default_factory=list)
    instance_space_config: InstanceSpaceConfig | None

    @classmethod
    def from_view(
        cls, view: View, instance_space_config: InstanceSpaceConfig | None
    ) -> ViewDefinition:
        aggregate_fields: list[FieldDefinition] = []
        search_fields: list[FieldDefinition] = []
        regular_fields: list[FieldDefinition] = []
        relation_fields: list[RelationDefinition] = []

        for property_name, view_property in view.properties.items():
            field_name = to_snake(property_name)
            is_reserved_name = field_name in python_keywords
            if is_reserved_name:
                field_name = f"{field_name}_"

            field_alias = (
                property_name
                if to_camel(field_name) != property_name or is_reserved_name
                else None
            )

            if isinstance(view_property, MappedProperty):
                mapped_field = _field_from_mapped_property(
                    field_name, field_alias, view_property
                )
                search_fields.append(mapped_field)

                if _is_aggregate_field(view_property, field_name, mapped_field.is_list):
                    aggregate_fields.append(
                        mapped_field.model_copy(
                            update={"is_nullable": True, "is_list": False}
                        )
                    )

                target_view = (
                    view_property.source.external_id if view_property.source else None
                )
                if target_view:
                    relation_fields.append(
                        RelationDefinition(
                            field_name=field_name,
                            property=field_alias or property_name,
                            target_view_external_id=target_view,
                            is_list=mapped_field.is_list,
                        )
                    )
                continue

            if isinstance(view_property, MultiReverseDirectRelation):
                continue

            if isinstance(view_property, SingleReverseDirectRelation | EdgeConnection):
                is_nullable = isinstance(view_property, SingleReverseDirectRelation)
                is_list = not is_nullable
                relation_fields.append(
                    RelationDefinition(
                        field_name=field_name,
                        property=field_alias or property_name,
                        target_view_external_id=view_property.source.external_id,
                        is_list=is_list,
                    )
                )
                regular_fields.append(
                    FieldDefinition(
                        field_name=field_name,
                        field_alias=field_alias,
                        field_type="InstanceId",
                        is_nullable=is_nullable,
                        is_list=is_list,
                    )
                )
                continue

            raise ValueError(f"Unsupported property type: {type(view_property)}")

        view_name = to_pascal(view.external_id)
        return cls(
            view_external_id=view.external_id,
            view_name=view_name,
            view_alias=(view.external_id if view_name != view.external_id else None),
            view_code=cls._extract_view_code(view),
            view_module_name=to_snake(view_name),
            aggregate_fields=aggregate_fields,
            search_fields=search_fields,
            regular_fields=regular_fields,
            relation_fields=relation_fields,
            instance_space_config=instance_space_config,
        )

    @classmethod
    def _extract_view_code(
        cls, view: View, code_annotation: str = "@code"
    ) -> str | None:
        if not view.description:
            return None

        description_metadata = view.description.split()
        if code_annotation not in description_metadata:
            return None

        code_idx = description_metadata.index(code_annotation)
        if code_idx + 1 >= len(description_metadata):
            return None

        view_code = description_metadata[code_idx + 1].strip()
        return view_code if view_code else None

    @property
    def view_config(self) -> str:
        return self._view_config()

    @property
    def aggregation_view_config(self) -> str:
        return self._view_config(group_by_behavior="NONE")

    def _view_config(self, *, group_by_behavior: str | None = None) -> str:
        fields = {"view_external_id": f'"{self.view_alias or self.view_name}"'}
        if self.view_code:
            fields["view_code"] = f'"{self.view_code}"'
        if self.instance_space_config and self.instance_space_config.instance_spaces:
            spaces = ", ".join(
                f'"{space}"' for space in self.instance_space_config.instance_spaces
            )
            fields["instance_spaces"] = f"[{spaces}]"
        elif (
            self.instance_space_config
            and self.instance_space_config.instance_spaces_prefix
        ):
            fields["instance_spaces_prefix"] = (
                f'"{self.instance_space_config.instance_spaces_prefix}"'
            )
        if group_by_behavior:
            fields["group_by_behavior"] = f'"{group_by_behavior}"'

        if group_by_behavior:
            fields_str = ",\n        ".join(
                f'"{key}": {value}' for key, value in fields.items()
            )
            return f"view_config = {{\n        {fields_str},\n    }}"

        fields_str = ", ".join(f'"{key}": {value}' for key, value in fields.items())
        return f"view_config = {{{fields_str}}}"

    @property
    def entity_fields(self) -> list[FieldDefinition]:
        relation_map = {
            r.field_name: to_pascal(r.target_view_external_id)
            for r in self.relation_fields
            if r.target_view_available
        }
        result = []
        for field in [*self.search_fields, *self.regular_fields]:
            if field.field_type == "InstanceId" and field.field_name in relation_map:
                result.append(
                    field.model_copy(
                        update={"concrete_type": relation_map[field.field_name]}
                    )
                )
            else:
                result.append(field)
        return result

    @property
    def used_filter_types(self) -> list[str]:
        types: set[str] = {"StringFilter"}
        for field in self.search_fields:
            ft = field.filter_type_name
            if ft:
                types.add(ft)
        return sorted(types)

    @property
    def typeddict_fields(self) -> list[str]:
        result: list[str] = []
        relation_fields_by_name = {
            relation.field_name: relation
            for relation in self.relation_fields
            if relation.target_view_available
        }
        rendered_properties: set[str] = set()
        for field in self.search_fields:
            ft = field.filter_type_name
            if ft:
                relation = relation_fields_by_name.get(field.field_name)
                property_ = field.field_alias or to_camel(field.field_name)
                if relation and not relation.is_list:
                    ft = f'"{ft} | {to_pascal(relation.target_view_external_id)}Filter"'
                result.append(f'        "{property_}": {ft},')
                rendered_properties.add(property_)
        for relation in self.relation_fields:
            if (
                relation.target_view_available
                and not relation.is_list
                and relation.property not in rendered_properties
            ):
                result.append(
                    f'        "{relation.property}": '
                    f'"{to_pascal(relation.target_view_external_id)}Filter",'
                )
                rendered_properties.add(relation.property)
        result.extend(
            [
                '        "externalId": StringFilter,',
                '        "space": StringFilter,',
            ]
        )
        return sorted(result)

    @property
    def query_property_type_name(self) -> str:
        return f"{self.view_name}QueryProperty"

    @property
    def query_property_literal(self) -> str:
        fields = [
            search_field.field_alias or to_camel(search_field.field_name)
            for search_field in self.search_fields
            if search_field.field_type == "str"
        ]
        fields_as_str = ", ".join(f'"{field}"' for field in fields)
        return f"Literal[{fields_as_str}]" if fields else "str"

    @property
    def group_by_property_type_name(self) -> str:
        return f"{self.view_name}GroupByProperty"

    @property
    def aggregation_property_type_name(self) -> str:
        return f"{self.view_name}AggregationProperty"

    @property
    def relation_type_imports(self) -> list[tuple[str, str, str]]:
        targets = {
            relation.target_view_external_id
            for relation in self.relation_fields
            if relation.target_view_available
            and to_pascal(relation.target_view_external_id) != self.view_name
        }
        return sorted(
            (
                to_snake(to_pascal(target)),
                to_pascal(target),
                f"{to_pascal(target)}Filter",
            )
            for target in targets
        )

    @property
    def filter_relation_type_imports(self) -> list[tuple[str, str, str]]:
        targets = {
            relation.target_view_external_id
            for relation in self.relation_fields
            if not relation.is_list
            and relation.target_view_available
            and to_pascal(relation.target_view_external_id) != self.view_name
        }
        return sorted(
            (
                to_snake(to_pascal(target)),
                to_pascal(target),
                f"{to_pascal(target)}Filter",
            )
            for target in targets
        )

    @property
    def group_by_property_literal(self) -> str:
        fields = [
            field.field_alias or to_camel(field.field_name)
            for field in self.aggregate_fields
        ]
        fields_as_str = ", ".join(f'"{field}"' for field in fields)
        return f"Literal[{fields_as_str}]" if fields else "str"

    @property
    def aggregate_property_literal(self) -> str:
        fields = [
            "externalId",
            "space",
            *[
                field.field_alias or to_camel(field.field_name)
                for field in self.aggregate_fields
            ],
        ]
        fields_as_str = ", ".join(f'"{field}"' for field in fields)
        return f"Literal[{fields_as_str}]"

    @property
    def include_property_type_name(self) -> str:
        return f"{self.view_name}IncludeProperty"

    @property
    def include_property_literal(self) -> str:
        fields = [
            relation.property
            for relation in self.relation_fields
            if relation.target_view_available
        ]
        fields_as_str = ", ".join(f'"{field}"' for field in fields)
        return f"Literal[{fields_as_str}]" if fields else "str"

    @property
    def relation_property_set(self) -> str:
        paths = self.all_relation_paths or [r.property for r in self.relation_fields]
        if not paths:
            return "frozenset()"
        fields = sorted(f'"{p}"' for p in paths)
        return "frozenset({" + ", ".join(fields) + "})"


def _field_from_mapped_property(
    field_name: str,
    field_alias: str | None,
    view_property: MappedProperty,
) -> FieldDefinition:
    base_type = mapping_types.get(view_property.type._type)
    if base_type is None:
        raise ValueError(f"Unsupported property type: {view_property.type._type}")

    is_list = (
        isinstance(view_property.type, ListablePropertyType)
        and view_property.type.is_list
    )
    return FieldDefinition(
        field_name=field_name,
        field_alias=field_alias,
        field_type=base_type,
        is_nullable=view_property.nullable,
        is_list=is_list,
    )


def _is_aggregate_field(
    view_property: MappedProperty, field_name: str, is_list: bool
) -> bool:
    return (
        not is_list
        and view_property.type._type in aggregate_group_types
        and field_name != "value"
    )


def _collect_nested_relation_paths(
    view_definitions_by_id: dict[str, ViewDefinition],
    view_external_id: str,
    prefix: str,
    visited: frozenset[str],
    depth: int = 0,
    max_depth: int = 2,
) -> list[str]:
    if depth >= max_depth:
        return []

    view_def = view_definitions_by_id.get(view_external_id)
    if not view_def:
        return []

    paths: list[str] = []
    for relation in view_def.relation_fields:
        if not relation.target_view_available:
            continue

        full_path = (
            f"{prefix}{NESTED_SEP}{relation.property}" if prefix else relation.property
        )
        paths.append(full_path)

        target_id = relation.target_view_external_id
        if target_id not in visited:
            paths.extend(
                _collect_nested_relation_paths(
                    view_definitions_by_id,
                    target_id,
                    full_path,
                    visited | {target_id},
                    depth + 1,
                    max_depth,
                )
            )

    return paths


def resolve_all_relation_paths(
    view_definitions: list[ViewDefinition],
) -> list[ViewDefinition]:
    by_id = {vd.view_external_id: vd for vd in view_definitions}
    view_definitions = [
        vd.model_copy(
            update={
                "relation_fields": [
                    relation.model_copy(
                        update={
                            "target_view_available": (
                                relation.target_view_external_id in by_id
                            )
                        }
                    )
                    for relation in vd.relation_fields
                ]
            }
        )
        for vd in view_definitions
    ]
    by_id = {vd.view_external_id: vd for vd in view_definitions}
    return [
        vd.model_copy(
            update={
                "all_relation_paths": _collect_nested_relation_paths(
                    by_id, vd.view_external_id, "", frozenset()
                )
            }
        )
        for vd in view_definitions
    ]
