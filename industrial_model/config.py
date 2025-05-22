from industrial_model.models import RootModel


class DataModelId(RootModel):
    external_id: str
    space: str
    version: str

    def as_tuple(self) -> tuple[str, str, str]:
        return self.space, self.external_id, self.version
