import asyncio

from cognite.client import AsyncCogniteClient
from cognite.client.data_classes.data_modeling import (
    View,
    ViewId,
)
from cognite.client.data_classes.data_modeling.views import ViewProperty

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

            views = dm.latest_version().views

            while True:
                new_dependency_view_ids = self._get_new_dependency_view_ids(views)
                if not new_dependency_view_ids:
                    break

                new_views = await self._cognite_client.data_modeling.views.retrieve(
                    ids=new_dependency_view_ids,
                )
                views.extend(new_views)

            self._views_as_dict = {view.external_id: view for view in views}

    def _get_new_dependency_view_ids(self, views: list[View]) -> list[ViewId]:
        view_ids = {view.external_id for view in views}
        views_from_dependencies = [
            self._try_extract_view_id(view_property)
            for view in views
            for view_property in view.properties.values()
        ]
        new_views: set[ViewId] = set()
        for views_dependency in views_from_dependencies:
            if (
                views_dependency
                and views_dependency.external_id not in view_ids
                and views_dependency not in new_views
            ):
                new_views.add(views_dependency)
        return list(new_views)

    def _try_extract_view_id(self, view_property: ViewProperty) -> ViewId | None:
        if hasattr(view_property, "source") and isinstance(
            view_property.source, ViewId
        ):
            return view_property.source
        return None
