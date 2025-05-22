from cognite.client.data_classes.data_modeling import (
    View,
)


class ViewMapper:
    def __init__(self, views: list[View]):
        self._views_as_dict = {view.external_id: view for view in views}

    def get_view(self, view_external_id: str) -> View:
        if view_external_id not in self._views_as_dict:
            raise ValueError(
                f"View {view_external_id} is not available in data model"
            )

        return self._views_as_dict[view_external_id]
