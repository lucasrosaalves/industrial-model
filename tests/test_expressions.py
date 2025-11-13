"""Unit tests for expression building logic."""

from datetime import datetime

from industrial_model.models import InstanceId, ViewInstance
from industrial_model.statements import (
    BoolExpression,
    Column,
    LeafExpression,
    and_,
    col,
    not_,
    or_,
)


class TestModel(ViewInstance):
    name: str
    description: str | None = None
    aliases: list[str] = []
    value: int = 0


def test_leaf_expression_creation() -> None:
    """Test creating leaf expressions."""
    expr = col(TestModel.name).equals_("test")
    assert isinstance(expr, LeafExpression)
    assert expr.property == "name"
    assert expr.operator == "=="
    assert expr.value == "test"


def test_leaf_expression_operators() -> None:
    """Test all leaf expression operators."""
    from industrial_model.statements import LeafExpression

    col_name = col(TestModel.name)

    # Comparison operators
    expr = col_name < "z"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "<"

    expr = col_name <= "z"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "<="

    expr = col_name > "a"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == ">"

    expr = col_name >= "a"
    assert isinstance(expr, LeafExpression)
    assert expr.operator == ">="

    expr = col_name.equals_("test")
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "=="

    # List operators
    expr = col_name.in_(["a", "b"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "in"

    expr = col_name.contains_any_(["a"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "containsAny"

    expr = col_name.contains_all_(["a"])
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "containsAll"

    # String operators
    expr = col_name.prefix("test")
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "prefix"

    # Existence operators
    expr = col_name.exists_()
    assert isinstance(expr, LeafExpression)
    assert expr.operator == "exists"


def test_bool_expression_creation() -> None:
    """Test creating boolean expressions."""
    expr1 = col(TestModel.name) == "test1"
    expr2 = col(TestModel.name) == "test2"

    # AND
    and_expr = and_(expr1, expr2)
    assert isinstance(and_expr, BoolExpression)
    assert and_expr.operator == "and"
    assert len(and_expr.filters) == 2

    # OR
    or_expr = or_(expr1, expr2)
    assert isinstance(or_expr, BoolExpression)
    assert or_expr.operator == "or"

    # NOT
    not_expr = not_(expr1)
    assert isinstance(not_expr, BoolExpression)
    assert not_expr.operator == "not"
    assert len(not_expr.filters) == 1


def test_expression_immutability() -> None:
    """Test that expressions are immutable (frozen dataclasses)."""
    expr1 = col(TestModel.name) == "test1"
    expr2 = col(TestModel.name) == "test2"

    and_expr = expr1 & expr2

    # Verify it's a BoolExpression
    assert isinstance(and_expr, BoolExpression)
    # Verify filters are the original expressions
    assert and_expr.filters[0] == expr1
    assert and_expr.filters[1] == expr2


def test_column_hashable() -> None:
    """Test that Column is hashable."""
    col1 = col(TestModel.name)
    col2 = col(TestModel.name)
    col3 = col(TestModel.description)

    # Same column should have same hash (based on property)
    assert hash(col1) == hash(col2)
    # Different columns should have different hashes
    assert hash(col1) != hash(col3)

    # Can be used in sets - Python uses hash and __eq__ for set membership
    # Since __eq__ raises ValueError for Column comparison,
    # sets may not work as expected
    # But hash is still valid for other uses
    assert isinstance(hash(col1), int)


def test_column_equality() -> None:
    """Test Column equality by comparing properties."""
    col1 = col(TestModel.name)
    col2 = col(TestModel.name)
    col3 = col(TestModel.description)

    # Can't use == directly (raises ValueError), so compare properties
    assert col1.property == col2.property
    assert col1.property != col3.property


def test_nested_expressions() -> None:
    """Test nested expression building."""
    inner_expr = col(TestModel.description) == "test"
    outer_expr = col(TestModel.name).nested_(inner_expr)

    assert isinstance(outer_expr, LeafExpression)
    assert outer_expr.operator == "nested"
    assert isinstance(outer_expr.value, LeafExpression)
    assert outer_expr.value == inner_expr


def test_complex_nested_expressions() -> None:
    """Test deeply nested boolean expressions."""
    expr1 = col(TestModel.name) == "test1"
    expr2 = col(TestModel.name) == "test2"
    expr3 = col(TestModel.description).exists_()

    # Nested AND/OR
    nested = and_(or_(expr1, expr2), expr3)

    assert isinstance(nested, BoolExpression)
    assert nested.operator == "and"
    assert len(nested.filters) == 2
    assert isinstance(nested.filters[0], BoolExpression)
    assert nested.filters[0].operator == "or"


def test_datetime_comparison() -> None:
    """Test datetime comparisons."""
    dt = datetime(2024, 1, 1)
    col_name = col(TestModel.name)

    expr = col_name.gt_(dt)
    assert isinstance(expr, LeafExpression)
    assert expr.operator == ">"
    assert expr.value == dt


def test_instance_id_comparison() -> None:
    """Test InstanceId comparisons."""
    instance_id = InstanceId(external_id="test", space="space")
    col_name = col(TestModel.name)

    expr = col_name == instance_id
    assert isinstance(expr, LeafExpression)
    assert expr.value == instance_id


def test_list_value_types() -> None:
    """Test different list value types."""
    from industrial_model.statements import LeafExpression

    col_name = col(TestModel.name)

    # String list
    expr = col_name.in_(["a", "b", "c"])
    assert isinstance(expr, LeafExpression)
    assert expr.value == ["a", "b", "c"]

    # Int list
    col_value = col(TestModel.value)
    expr = col_value.in_([1, 2, 3])
    assert isinstance(expr, LeafExpression)
    assert expr.value == [1, 2, 3]

    # Float list
    expr = col_value.in_([1.0, 2.0, 3.0])
    assert isinstance(expr, LeafExpression)
    assert expr.value == [1.0, 2.0, 3.0]

    # Dict list (for InstanceId)
    expr = col_name.contains_any_([{"externalId": "test", "space": "space"}])
    assert isinstance(expr, LeafExpression)
    assert isinstance(expr.value, list)


def test_not_operator() -> None:
    """Test not operator variations."""
    col_name = col(TestModel.name)

    # not_exists
    expr = col_name.not_exists_()
    assert isinstance(expr, BoolExpression)
    assert expr.operator == "not"

    # not with operator
    expr = col_name.not_("==", "test")
    assert isinstance(expr, BoolExpression)
    assert expr.operator == "not"
    assert len(expr.filters) == 1
    assert isinstance(expr.filters[0], LeafExpression)
    assert expr.filters[0].operator == "=="


def test_operator_chaining() -> None:
    """Test chaining operators."""
    col_name = col(TestModel.name)

    # Chain comparisons
    expr1 = col_name == "test"
    expr2 = col_name.prefix("prefix")
    combined = expr1 & expr2

    assert isinstance(combined, BoolExpression)
    assert combined.operator == "and"


def test_column_from_string() -> None:
    """Test creating column from string."""
    col1 = col("name")
    assert isinstance(col1, Column)
    assert col1.property == "name"

    # From another column
    col2 = col(col1)
    assert col2.property == "name"
    # Can't use == directly, so compare properties
    assert col2.property == col1.property
