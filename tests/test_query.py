from typing import Annotated

from industrial_model.queries import BaseQuery, BoolQueryParam, QueryParam, SortParam
from industrial_model.statements import BoolExpression
from tests.models import CogniteDescribable


class DescribableEntityQuery(BaseQuery):
    external_id_in: Annotated[
        list[str] | None,
        QueryParam("externalId", "in"),
    ] = None

    name_eq: Annotated[
        str | None,
        QueryParam("name", "eq"),
    ] = None

    sort_by: Annotated[
        str | None,
        SortParam("ascending"),
    ] = None
    or_: Annotated["DescribableEntityQuery | None", BoolQueryParam("or")] = None


def test_query() -> None:
    statement = DescribableEntityQuery().to_statement(CogniteDescribable)
    assert len(statement.get_values().where_clauses) == 0
    assert len(statement.get_values().sort_clauses) == 0

    statement = DescribableEntityQuery(sort_by="name").to_statement(CogniteDescribable)
    assert len(statement.get_values().where_clauses) == 0
    assert len(statement.get_values().sort_clauses) == 1

    statement = DescribableEntityQuery(
        external_id_in=["123"], name_eq="34"
    ).to_statement(CogniteDescribable)
    assert len(statement.get_values().where_clauses) == 2
    assert len(statement.get_values().sort_clauses) == 0

    statement = DescribableEntityQuery(
        or_=DescribableEntityQuery(name_eq="Test", external_id_in=["456"]),
    ).to_statement(CogniteDescribable)

    assert len(statement.get_values().where_clauses) == 1
    assert len(statement.get_values().sort_clauses) == 0

    target = statement.get_values().where_clauses[0]
    assert isinstance(target, BoolExpression)
    assert len(target.filters) == 2
