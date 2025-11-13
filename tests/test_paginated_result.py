"""Unit tests for PaginatedResult."""

from industrial_model import PaginatedResult, ViewInstance


class TestModel(ViewInstance):
    name: str


def test_paginated_result_creation() -> None:
    """Test creating a PaginatedResult."""
    data = [
        TestModel(external_id="1", space="space", name="Test1"),
        TestModel(external_id="2", space="space", name="Test2"),
    ]

    result = PaginatedResult(
        data=data,
        has_next_page=True,
        next_cursor="cursor123",
    )

    assert len(result.data) == 2
    assert result.has_next_page is True
    assert result.next_cursor == "cursor123"


def test_paginated_result_no_next_page() -> None:
    """Test PaginatedResult with no next page."""
    data = [TestModel(external_id="1", space="space", name="Test1")]

    result = PaginatedResult(
        data=data,
        has_next_page=False,
        next_cursor=None,
    )

    assert result.has_next_page is False
    assert result.next_cursor is None


def test_paginated_result_first_or_default() -> None:
    """Test first_or_default method."""
    data = [
        TestModel(external_id="1", space="space", name="Test1"),
        TestModel(external_id="2", space="space", name="Test2"),
    ]

    result = PaginatedResult(
        data=data,
        has_next_page=False,
        next_cursor=None,
    )

    first = result.first_or_default()
    assert first is not None
    assert first == data[0]
    assert first.name == "Test1"


def test_paginated_result_first_or_default_empty() -> None:
    """Test first_or_default with empty data."""
    result: PaginatedResult[TestModel] = PaginatedResult(
        data=[],
        has_next_page=False,
        next_cursor=None,
    )

    first = result.first_or_default()
    assert first is None


def test_paginated_result_empty() -> None:
    """Test empty PaginatedResult."""
    result: PaginatedResult[TestModel] = PaginatedResult(
        data=[],
        has_next_page=False,
        next_cursor=None,
    )

    assert len(result.data) == 0
    assert result.has_next_page is False
    assert result.next_cursor is None
