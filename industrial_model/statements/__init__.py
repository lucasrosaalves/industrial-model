from dataclasses import dataclass, field
from typing import Any, Generic, Self, TypeVar

from industrial_model.constants import DEFAULT_LIMIT, SORT_DIRECTION

from .expressions import (
    BoolExpression,
    Column,
    Expression,
    LeafExpression,
    and_,
    col,
    not_,
    or_,
)

T = TypeVar("T")


@dataclass
class Statement(Generic[T]):
    entity: type[T] = field(init=True)
    where_clauses: list[Expression] = field(init=False, default_factory=list)
    sort_clauses: list[tuple[Column, SORT_DIRECTION]] = field(
        init=False, default_factory=list
    )
    limit_: int = field(init=False, default=DEFAULT_LIMIT)
    cursor_: str | None = field(init=False, default=None)

    def where(self, *expressions: bool | Expression) -> Self:
        for expression in expressions:
            assert isinstance(expression, Expression)
            self.where_clauses.append(expression)
        return self

    def asc(self, property: Any) -> Self:
        self.sort_clauses.append((Column(property), "ascending"))
        return self

    def desc(self, property: Any) -> Self:
        self.sort_clauses.append((Column(property), "descending"))
        return self

    def sort(self, property: Any, direction: SORT_DIRECTION) -> Self:
        self.sort_clauses.append((Column(property), direction))
        return self

    def limit(self, limit: int) -> Self:
        self.limit_ = limit
        return self

    def cursor(self, cursor: str | None) -> Self:
        self.cursor_ = cursor
        return self


def select(entity: type[T]) -> Statement[T]:
    return Statement(entity)


__all__ = [
    "Statement",
    "select",
    "Column",
    "col",
    "Expression",
    "LeafExpression",
    "BoolExpression",
    "and_",
    "not_",
    "or_",
]
