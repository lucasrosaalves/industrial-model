import asyncio

from cognite.client import AsyncCogniteClient
from cognite.client.data_classes.data_modeling import (
    View,
)

from industrial_model.config import DataModelId


class ViewMapper:
    def __init__(self, cognite_client: AsyncCogniteClient, data_model_id: DataModelId):
        self._cognite_client = cognite_client
        self._data_model_id = data_model_id
        self._views_as_dict: dict[str, View] | None = None
        self._lock = asyncio.Lock()

    def get_view(self, view_external_id: str) -> View:
        if self._views_as_dict is None:
            raise RuntimeError(
                "ViewMapper not loaded. Call load_views() before using get_view()."
            )
        if view_external_id not in self._views_as_dict:
            raise ValueError(f"View {view_external_id} is not available in data model")
        return self._views_as_dict[view_external_id]

    async def load_views(self) -> None:
        if self._views_as_dict is not None:
            return

        async with self._lock:
            if self._views_as_dict is not None:
                return

            dm = await self._cognite_client.data_modeling.data_models.retrieve(
                ids=self._data_model_id.as_tuple(),
                inline_views=True,
            )
            self._views_as_dict = {
                view.external_id: view for view in dm.latest_version().views
            }
