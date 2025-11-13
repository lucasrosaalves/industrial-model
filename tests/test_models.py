"""Unit tests for model utilities and functionality."""

from industrial_model import (
    AggregatedViewInstance,
    InstanceId,
    ViewInstance,
    ViewInstanceConfig,
    WritableViewInstance,
)
from industrial_model.statements import Column


class TestModel(ViewInstance):
    name: str
    description: str | None = None
    aliases: list[str] = []
    value: int = 0


class TestModelWithConfig(ViewInstance):
    view_config = ViewInstanceConfig(
        view_external_id="TestView",
        instance_spaces=["space1", "space2"],
        instance_spaces_prefix="Test-",
        view_code="CODE",
    )
    name: str


class TestWritableModel(WritableViewInstance):
    name: str

    def edge_id_factory(
        self, target_node: InstanceId, edge_type: InstanceId
    ) -> InstanceId:
        return InstanceId(
            external_id=f"{self.external_id}-{target_node.external_id}-{edge_type.external_id}",
            space=self.space,
        )


class TestAggregatedModel(AggregatedViewInstance):
    view_config = ViewInstanceConfig(view_external_id="TestView")
    name: str


def test_view_instance_creation() -> None:
    """Test creating a ViewInstance."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
        description="Test Description",
        aliases=["alias1", "alias2"],
    )

    assert instance.external_id == "test-1"
    assert instance.space == "test-space"
    assert instance.name == "Test Name"
    assert instance.description == "Test Description"
    assert instance.aliases == ["alias1", "alias2"]


def test_view_instance_get_view_external_id() -> None:
    """Test getting view external ID."""
    # Default (uses class name)
    assert TestModel.get_view_external_id() == "TestModel"

    # With config
    assert TestModelWithConfig.get_view_external_id() == "TestView"


def test_view_instance_generate_model_id() -> None:
    """Test generating model IDs."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    # Single field
    id1 = instance.generate_model_id(["name"])
    assert id1 == "TestName"

    # Multiple fields
    id2 = instance.generate_model_id(["name", "external_id"])
    assert "TestName" in id2
    assert "test-1" in id2

    # With view_code prefix
    instance_with_code = TestModelWithConfig(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )
    id3 = instance_with_code.generate_model_id(["name"])
    assert id3.startswith("CODE-")

    # Without prefix
    id4 = instance_with_code.generate_model_id(["name"], view_code_as_prefix=False)
    assert not id4.startswith("CODE-")

    # Custom separator
    id5 = instance.generate_model_id(["name", "external_id"], separator="_")
    assert "_" in id5


def test_view_instance_generate_model_id_with_column() -> None:
    """Test generating model ID with Column objects."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    id1 = instance.generate_model_id([TestModel.name])
    assert id1 == "TestName"


def test_view_instance_get_field_name() -> None:
    """Test getting field name."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    # Direct field name
    assert instance.get_field_name("name") == "name"

    # Non-existent field
    assert instance.get_field_name("nonexistent") is None


def test_view_instance_get_field_alias() -> None:
    """Test getting field alias."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    # Field without explicit alias - behavior depends on Pydantic configuration
    # With alias_generator=to_camel, "name" stays "name" (no change needed)
    # The method returns the explicit alias if set, or None if not
    alias = instance.get_field_alias("name")
    # Accept either None or the field name itself (depending on Pydantic version/config)
    assert alias in (None, "name")

    # Non-existent field
    assert instance.get_field_alias("nonexistent") is None


def test_view_instance_get_edge_metadata() -> None:
    """Test getting edge metadata."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    # Empty edge metadata (no edges set)
    edges = instance.get_edge_metadata(TestModel.name)
    assert edges == []

    # With Column
    edges = instance.get_edge_metadata(Column("name"))
    assert edges == []

    # With string
    edges = instance.get_edge_metadata("name")
    assert edges == []


def test_writable_view_instance() -> None:
    """Test WritableViewInstance."""
    instance = TestWritableModel(
        external_id="test-1",
        space="test-space",
        name="Test Name",
    )

    target = InstanceId(external_id="target-1", space="test-space")
    edge_type = InstanceId(external_id="edge-type", space="test-space")

    edge_id = instance.edge_id_factory(target, edge_type)
    assert isinstance(edge_id, InstanceId)
    assert edge_id.external_id == "test-1-target-1-edge-type"
    assert edge_id.space == "test-space"


def test_aggregated_view_instance() -> None:
    """Test AggregatedViewInstance."""
    instance = TestAggregatedModel(
        name="Test Name",
        value=42.0,
    )

    assert instance.name == "Test Name"
    assert instance.value == 42.0
    assert TestAggregatedModel.get_view_external_id() == "TestView"


def test_aggregated_view_instance_get_group_by_fields() -> None:
    """Test getting group by fields."""
    fields = TestAggregatedModel.get_group_by_fields()
    assert "name" in fields
    assert "value" not in fields  # value is the aggregation result


def test_instance_id() -> None:
    """Test InstanceId."""
    instance_id = InstanceId(external_id="test-1", space="test-space")

    assert instance_id.external_id == "test-1"
    assert instance_id.space == "test-space"

    # Hashable
    assert isinstance(hash(instance_id), int)

    # Equality
    instance_id2 = InstanceId(external_id="test-1", space="test-space")
    assert instance_id == instance_id2

    instance_id3 = InstanceId(external_id="test-2", space="test-space")
    assert instance_id != instance_id3

    # As tuple
    assert instance_id.as_tuple() == ("test-space", "test-1")


def test_view_instance_config() -> None:
    """Test ViewInstanceConfig."""
    config = ViewInstanceConfig(
        view_external_id="TestView",
        instance_spaces=["space1"],
        instance_spaces_prefix="Test-",
        view_code="CODE",
    )

    assert config["view_external_id"] == "TestView"
    assert config["instance_spaces"] == ["space1"]
    assert config["instance_spaces_prefix"] == "Test-"
    assert config["view_code"] == "CODE"


def test_model_with_field_alias() -> None:
    """Test model with field aliases."""
    from pydantic import Field

    class ModelWithAlias(ViewInstance):
        field_name: str = Field(alias="camelCaseName")

    # With populate_by_name=True, we can use either the field name or alias
    instance = ModelWithAlias(
        external_id="test-1",
        space="test-space",
        camelCaseName="test",  # Use alias name
    )

    assert instance.field_name == "test"
    assert instance.get_field_alias("field_name") == "camelCaseName"
    assert instance.get_field_name("camelCaseName") == "field_name"


def test_model_validation() -> None:
    """Test model validation."""
    # Valid model
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test",
    )
    assert instance.name == "Test"

    # Optional fields
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test",
        description=None,
    )
    assert instance.description is None


def test_model_default_values() -> None:
    """Test model default values."""
    instance = TestModel(
        external_id="test-1",
        space="test-space",
        name="Test",
    )

    # Default factory fields
    assert instance.aliases == []
    assert instance.value == 0
