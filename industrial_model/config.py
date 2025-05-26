from cognite.client.data_classes.data_modeling import View
from pydantic import BaseModel, ConfigDict, Field


class DataModelId(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    external_id: str
    space: str
    version: str

    views: list[View] | None = Field(default=None)
    instance_spaces: list[str] | None = Field(default=None)

    def as_tuple(self) -> tuple[str, str, str]:
        return self.space, self.external_id, self.version
