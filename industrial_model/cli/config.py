from pathlib import Path

from pydantic import BaseModel, Field

from industrial_model.config import DataModelId


class InstanceSpaceConfig(BaseModel):
    view_or_space_external_id: str
    instance_spaces: list[str] | None = None
    instance_spaces_prefix: str | None = None


class GeneratorConfig(BaseModel):
    client_name: str
    output_path: Path
    data_model: DataModelId
    token: str | None = None
    project: str | None = None
    base_url: str | None = None
    instance_space_configs: list[InstanceSpaceConfig] = Field(default_factory=list)
    view_mapper_cache: bool = True

    @classmethod
    def from_token(
        cls,
        *,
        token: str,
        project: str,
        base_url: str,
        client_name: str,
        output_path: Path,
        data_model: DataModelId,
        view_mapper_cache: bool = True,
    ) -> "GeneratorConfig":
        return cls(
            client_name=client_name,
            output_path=output_path,
            token=token,
            project=project,
            base_url=base_url,
            data_model=data_model,
            view_mapper_cache=view_mapper_cache,
        )
