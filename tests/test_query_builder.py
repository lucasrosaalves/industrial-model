from industrial_model.queries.builder import build_query_statement
from tests.models import CogniteDescribable


def test_build_query_statement_without_sort() -> None:
    statement = build_query_statement(CogniteDescribable)

    assert statement.get_values().sort_clauses == []


def test_build_query_statement_applies_single_sort() -> None:
    statement = build_query_statement(
        CogniteDescribable,
        sort={"name": "ascending"},
    )

    values = statement.get_values()
    assert len(values.sort_clauses) == 1
    assert values.sort_clauses[0][0].property == "name"
    assert values.sort_clauses[0][1] == "ascending"


def test_build_query_statement_applies_multiple_sorts() -> None:
    statement = build_query_statement(
        CogniteDescribable,
        sort={
            "name": "descending",
            "externalId": "ascending",
        },
    )

    values = statement.get_values()
    clauses = [
        (column.property, direction) for column, direction in values.sort_clauses
    ]
    assert clauses == [
        ("name", "descending"),
        ("externalId", "ascending"),
    ]
