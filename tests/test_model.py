from industrial_model import ViewInstance, ViewInstanceConfig


class Model1(ViewInstance):
    name: str
    value: int = 0


class Model2(ViewInstance):
    view_config = ViewInstanceConfig(view_code="CODE123")
    name: str
    description: str | None = None


def test_id_generator_single_field() -> None:
    """Test ID generation with single field."""
    model1 = Model1(external_id="", space="", name="test1")
    assert model1.generate_model_id(["name"]) == "test1"


def test_id_generator_with_view_code() -> None:
    """Test ID generation with view code prefix."""
    model2 = Model2(external_id="", space="", name="test2")
    assert model2.generate_model_id(["name"]) == "CODE123-test2"


def test_id_generator_with_column() -> None:
    """Test ID generation with Column object."""
    model3 = Model2(external_id="", space="", name="test3")
    assert model3.generate_model_id([Model2.name]) == "CODE123-test3"


def test_id_generator_multiple_fields() -> None:
    """Test ID generation with multiple fields."""
    model1 = Model1(external_id="test-id", space="", name="test1", value=42)
    id_result = model1.generate_model_id(["name", "external_id"])
    assert "test1" in id_result
    assert "test-id" in id_result


def test_id_generator_custom_separator() -> None:
    """Test ID generation with custom separator."""
    model1 = Model1(external_id="test-id", space="", name="test1")
    id_result = model1.generate_model_id(["name", "external_id"], separator="_")
    assert "_" in id_result


def test_id_generator_without_prefix() -> None:
    """Test ID generation without view code prefix."""
    model2 = Model2(external_id="", space="", name="test2")
    id_result = model2.generate_model_id(["name"], view_code_as_prefix=False)
    assert id_result == "test2"
    assert not id_result.startswith("CODE123")
