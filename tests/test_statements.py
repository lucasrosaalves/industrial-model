"""Unit tests for statement building logic."""

from industrial_model.models import ViewInstance
from industrial_model.statements import (
    AggregationStatement,
    BoolExpression,
    Column,
    LeafExpression,
    SearchStatement,
    Statement,
    aggregate,
    and_,
    col,
    not_,
    or_,
    search,
    select,
)


class TestModel(ViewInstance):
    name: str
    description: str | None = None
    aliases: list[str] = []


def test_select_statement_creation() -> None:
    """Test creating a select statement."""
    statement = select(TestModel)
    assert isinstance(statement, Statement)
    assert statement.entity == TestModel
    assert len(statement.get_values().where_clauses) == 0
    assert statement.get_values().limit == 1000  # DEFAULT_LIMIT


def test_statement_where() -> None:
    """Test adding where clauses to a statement."""
    statement = select(TestModel).where(col(TestModel.name) == "test")

    values = statement.get_values()
    assert len(values.where_clauses) == 1
    assert isinstance(values.where_clauses[0], LeafExpression)
    assert values.where_clauses[0].operator == "=="
    assert values.where_clauses[0].value == "test"


def test_statement_multiple_where() -> None:
    """Test adding multiple where clauses."""
    statement = (
        select(TestModel)
        .where(col(TestModel.name) == "test")
        .where(col(TestModel.description).exists_())
    )

    values = statement.get_values()
    assert len(values.where_clauses) == 2


def test_statement_limit() -> None:
    """Test setting limit on a statement."""
    statement = select(TestModel).limit(50)
    assert statement.get_values().limit == 50


def test_statement_sorting() -> None:
    """Test sorting operations."""
    # Ascending
    statement = select(TestModel).asc(TestModel.name)
    values = statement.get_values()
    assert len(values.sort_clauses) == 1
    assert values.sort_clauses[0][1] == "ascending"
    assert values.sort_clauses[0][0].property == "name"

    # Descending
    statement = select(TestModel).desc(TestModel.name)
    values = statement.get_values()
    assert values.sort_clauses[0][1] == "descending"

    # Multiple sorts
    statement = select(TestModel).asc(TestModel.name).desc(TestModel.description)
    values = statement.get_values()
    assert len(values.sort_clauses) == 2


def test_statement_cursor() -> None:
    """Test cursor pagination."""
    statement = select(TestModel).cursor("cursor123")
    assert statement.get_values().cursor == "cursor123"

    statement = statement.cursor(None)
    assert statement.get_values().cursor is None


def test_statement_where_edge() -> None:
    """Test edge filtering."""
    statement = select(TestModel).where_edge(
        TestModel.name, col(TestModel.name) == "test"
    )

    values = statement.get_values()
    assert len(values.where_edge_clauses) == 1
    assert values.where_edge_clauses[0][0].property == "name"
    assert len(values.where_edge_clauses[0][1]) == 1


def test_search_statement_creation() -> None:
    """Test creating a search statement."""
    statement = search(TestModel)
    assert isinstance(statement, SearchStatement)
    assert statement.entity == TestModel


def test_search_statement_query_by() -> None:
    """Test search query_by method."""
    statement = search(TestModel).query_by("test query")

    values = statement.get_values()
    assert values.query == "test query"
    assert values.query_properties is None
    assert values.search_operator is None


def test_search_statement_query_by_with_properties() -> None:
    """Test search with specific properties."""
    statement = search(TestModel).query_by(
        "test query",
        query_properties=[TestModel.name, TestModel.description],
        operation="AND",
    )

    values = statement.get_values()
    assert values.query == "test query"
    assert values.query_properties == ["name", "description"]
    assert values.search_operator == "AND"


def test_aggregate_statement_creation() -> None:
    """Test creating an aggregation statement."""
    statement = aggregate(TestModel, "count")
    assert isinstance(statement, AggregationStatement)
    assert statement.entity == TestModel
    assert statement.aggregate == "count"


def test_aggregate_statement_group_by() -> None:
    """Test aggregation with group by."""
    statement = aggregate(TestModel, "count").group_by(col(TestModel.name))

    values = statement.get_values()
    assert values.group_by_properties is not None
    assert len(values.group_by_properties) == 1
    assert values.group_by_properties[0].property == "name"


def test_aggregate_statement_aggregate_by() -> None:
    """Test setting aggregation property."""
    statement = aggregate(TestModel, "sum").aggregate_by(TestModel.name)

    values = statement.get_values()
    assert values.aggregation_property.property == "name"


def test_aggregate_statement_where() -> None:
    """Test aggregation with filters."""
    statement = aggregate(TestModel, "count").where(col(TestModel.name) == "test")

    values = statement.get_values()
    assert len(values.where_clauses) == 1


def test_aggregate_statement_limit() -> None:
    """Test aggregation with limit."""
    statement = aggregate(TestModel, "count").limit(10)
    assert statement.get_values().limit == 10


def test_column_creation() -> None:
    """Test Column creation."""
    col1 = col("name")
    assert isinstance(col1, Column)
    assert col1.property == "name"

    col2 = col(TestModel.name)
    assert isinstance(col2, Column)
    assert col2.property == "name"


def test_column_comparison_operators() -> None:
    """Test column comparison operators."""
    col_name = col(TestModel.name)

    # Equality
    expr = col_name == "test"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "=="
    assert expr.value == "test"

    # Inequality
    expr = col_name != "test"
    assert isinstance(expr, BoolExpression)
    assert expr.operator == "not"

    # Less than
    expr = col_name < "z"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "<"

    # Greater than
    expr = col_name > "a"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == ">"

    # Less than or equal
    expr = col_name <= "z"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "<="

    # Greater than or equal
    expr = col_name >= "a"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == ">="


def test_column_list_operators() -> None:
    """Test column list operators."""
    col_aliases = col(TestModel.aliases)

    # In
    expr = col_aliases.in_(["a", "b"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "in"
    assert expr.value == ["a", "b"]

    # Contains any
    expr = col_aliases.contains_any_(["a", "b"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "containsAny"

    # Contains all
    expr = col_aliases.contains_all_(["a", "b"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "containsAll"


def test_column_string_operators() -> None:
    """Test column string operators."""
    col_name = col(TestModel.name)

    # Prefix
    expr = col_name.prefix("test")
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "prefix"
    assert expr.value == "test"


def test_column_existence_operators() -> None:
    """Test column existence operators."""
    col_desc = col(TestModel.description)

    # Exists
    expr = col_desc.exists_()
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "exists"
    assert expr.value is None

    # Not exists
    expr = col_desc.not_exists_()
    assert isinstance(expr, BoolExpression)
    assert expr.operator == "not"


def test_column_nested_operator() -> None:
    """Test nested query operator."""
    col_name = col(TestModel.name)
    nested_expr = col(TestModel.description) == "test"

    expr = col_name.nested_(nested_expr)
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "nested"
    assert isinstance(expr.value, LeafExpression)


def test_boolean_operators() -> None:
    """Test boolean operators."""
    expr1 = col(TestModel.name) == "test1"
    expr2 = col(TestModel.name) == "test2"

    # AND with &
    and_expr = expr1 & expr2
    assert isinstance(and_expr, BoolExpression)
    assert and_expr.operator == "and"
    assert len(and_expr.filters) == 2

    # OR with |
    or_expr = expr1 | expr2
    assert isinstance(or_expr, BoolExpression)
    assert or_expr.operator == "or"

    # and_() function
    and_expr = and_(expr1, expr2)
    assert isinstance(and_expr, BoolExpression)
    assert and_expr.operator == "and"

    # or_() function
    or_expr = or_(expr1, expr2)
    assert isinstance(or_expr, BoolExpression)
    assert or_expr.operator == "or"

    # not_() function
    not_expr = not_(expr1)
    assert isinstance(not_expr, BoolExpression)
    assert not_expr.operator == "not"


def test_complex_boolean_expressions() -> None:
    """Test complex boolean expression combinations."""
    expr1 = col(TestModel.name) == "test1"
    expr2 = col(TestModel.name) == "test2"
    expr3 = col(TestModel.description).exists_()

    # Complex AND/OR
    complex_expr = (expr1 | expr2) & expr3
    assert isinstance(complex_expr, BoolExpression)
    assert complex_expr.operator == "and"
    assert len(complex_expr.filters) == 2

    # Nested with functions
    complex_expr = and_(or_(expr1, expr2), expr3)
    assert isinstance(complex_expr, BoolExpression)
    assert complex_expr.operator == "and"


def test_statement_fluent_chaining() -> None:
    """Test fluent API chaining."""
    statement = (
        select(TestModel)
        .where(col(TestModel.name) == "test")
        .where(col(TestModel.description).exists_())
        .asc(TestModel.name)
        .desc(TestModel.description)
        .limit(50)
        .cursor("cursor123")
    )

    values = statement.get_values()
    assert len(values.where_clauses) == 2
    assert len(values.sort_clauses) == 2
    assert values.limit == 50
    assert values.cursor == "cursor123"
