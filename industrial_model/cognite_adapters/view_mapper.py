from threading import Lock

from cognite.client import CogniteClient
from cognite.client.data_classes.data_modeling import (
    View,
)

from industrial_model.config import DataModelId


class ViewMapper:
    def __init__(
        self, cognite_client: CogniteClient, data_model_id: DataModelId
    ):
        self._cognite_client = cognite_client
        self._data_model_id = data_model_id
        self._views_as_dict: dict[str, View] | None = None

        if data_model_id.views:
            self._views_as_dict = {
                view.external_id: view for view in data_model_id.views
            }

        self._lock = Lock()

    def get_view(self, view_external_id: str) -> View:
        views = self._load_views()
        if view_external_id not in views:
            raise ValueError(
                f"View {view_external_id} is not available in data model"
            )

        return views[view_external_id]

    def _load_views(self) -> dict[str, View]:
        if self._views_as_dict:
            return self._views_as_dict

        with self._lock:
            if self._views_as_dict:
                return self._views_as_dict

            dm = self._cognite_client.data_modeling.data_models.retrieve(
                ids=self._data_model_id.as_tuple(),
                inline_views=True,
            ).latest_version()

            views = {view.external_id: view for view in dm.views}
            self._views_as_dict = views
            return views
