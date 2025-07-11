from pydantic import BaseModel, ConfigDict


class DataModelId(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    external_id: str
    space: str
    version: str

    def as_tuple(self) -> tuple[str, str, str]:
        return self.space, self.external_id, self.version
