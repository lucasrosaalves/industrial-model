from typing import Annotated

from industrial_model.queries import BaseQuery
from industrial_model.queries.params import BoolQueryParam, QueryParam, SortParam
from industrial_model.statements.expressions import BoolExpression
from tests.models import ReportingSite


class ReportingSiteQuery(BaseQuery):
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
    or_: Annotated["ReportingSiteQuery | None", BoolQueryParam("or")] = None


def test_query() -> None:
    statement = ReportingSiteQuery().to_statement(ReportingSite)
    assert len(statement.get_values().where_clauses) == 0
    assert len(statement.get_values().sort_clauses) == 0

    statement = ReportingSiteQuery(sort_by="name").to_statement(ReportingSite)
    assert len(statement.get_values().where_clauses) == 0
    assert len(statement.get_values().sort_clauses) == 1

    statement = ReportingSiteQuery(external_id_in=["123"], name_eq="34").to_statement(
        ReportingSite
    )
    assert len(statement.get_values().where_clauses) == 2
    assert len(statement.get_values().sort_clauses) == 0

    statement = ReportingSiteQuery(
        or_=ReportingSiteQuery(name_eq="Test", external_id_in=["456"]),
    ).to_statement(ReportingSite)

    assert len(statement.get_values().where_clauses) == 1
    assert len(statement.get_values().sort_clauses) == 0

    target = statement.get_values().where_clauses[0]
    assert isinstance(target, BoolExpression)
    assert len(target.filters) == 2
