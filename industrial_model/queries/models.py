from industrial_model.models import RootModel, TViewInstance
from industrial_model.statements import Statement

from .params import NestedQueryParam, QueryParam, SortParam


class BaseQuery(RootModel):
    def to_statement(
        self, entity: type[TViewInstance]
    ) -> Statement[TViewInstance]:
        statement = Statement(entity)

        for key, item in self.__class__.model_fields.items():
            values = getattr(self, key)
            if not values:
                continue
            for metadata_item in item.metadata:
                if isinstance(metadata_item, SortParam):
                    statement.sort(values, metadata_item.direction)
                elif isinstance(metadata_item, QueryParam | NestedQueryParam):
                    statement.where(metadata_item.to_expression(values))

        return statement


class BasePaginatedQuery(BaseQuery):
    limit: int = 1000
    cursor: str | None = None

    def to_statement(
        self, entity: type[TViewInstance]
    ) -> Statement[TViewInstance]:
        statement = super().to_statement(entity)
        statement.limit(self.limit)
        statement.cursor(self.cursor)

        return statement
