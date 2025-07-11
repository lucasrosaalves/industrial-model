from industrial_model import ViewInstance, ViewInstanceConfig


class Model1(ViewInstance):
    name: str


class Model2(ViewInstance):
    view_config = ViewInstanceConfig(view_code="CODE123")
    name: str


def test_id_generator() -> None:
    model1 = Model1(external_id="", space="", name="test1")
    assert model1.generate_model_id(["name"]) == "test1"

    model2 = Model2(external_id="", space="", name="test2")
    assert model2.generate_model_id(["name"]) == "CODE123-test2"

    model3 = Model2(external_id="", space="", name="test3")
    assert model3.generate_model_id([Model2.name]) == "CODE123-test3"
