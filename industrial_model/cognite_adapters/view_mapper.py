import asyncio
from collections.abc import Mapping, Sequence
from typing import Any, Self

from cognite.client import AsyncCogniteClient
from cognite.client.data_classes.data_modeling import (
    PropertyId,
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
        return _require_view(self._views_as_dict, view_external_id)

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
                new_dependency_view_ids = collect_new_dependency_view_ids(views)
                if not new_dependency_view_ids:
                    break

                new_views = await self._cognite_client.data_modeling.views.retrieve(
                    ids=new_dependency_view_ids,
                )
                views.extend(new_views)

            self._views_as_dict = {view.external_id: view for view in views}


class ViewMapperCache(ViewMapper):
    def __init__(self, views: Sequence[View] | Mapping[str, View]):
        self._views_as_dict = _index_views(views)
        self._lock = asyncio.Lock()

    async def load_views(self) -> None:
        return

    @classmethod
    def from_dumps(cls, dumps: Sequence[dict[str, Any]]) -> Self:
        return cls([View.load(item) for item in dumps])


def collect_new_dependency_view_ids(views: Sequence[View]) -> list[ViewId]:
    view_ids = {view.external_id for view in views}
    views_from_dependencies = [
        view_id_
        for view in views
        for view_property in view.properties.values()
        for view_id_ in _try_extract_view_ids(view_property)
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


def _try_extract_view_ids(view_property: ViewProperty) -> list[ViewId]:
    entries: set[ViewId] = set()

    if hasattr(view_property, "source") and isinstance(view_property.source, ViewId):
        entries.add(view_property.source)

    if (
        hasattr(view_property, "through")
        and isinstance(view_property.through, PropertyId)
        and isinstance(view_property.through.source, ViewId)
    ):
        entries.add(view_property.through.source)

    return list(entries)


def _index_views(views: Sequence[View] | Mapping[str, View]) -> dict[str, View]:
    if isinstance(views, Mapping):
        return dict(views)
    return {view.external_id: view for view in views}


def _require_view(views: dict[str, View], view_external_id: str) -> View:
    if view_external_id not in views:
        raise ValueError(f"View {view_external_id} is not available in data model")
    return views[view_external_id]
