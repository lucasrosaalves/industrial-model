from cognite.client.config import global_config

from industrial_model import AsyncEngine, DataModelId, Engine
from industrial_model.engines._internal import generate_engine_params_from_user_token

DATA_MODEL_ID = DataModelId(
    external_id="CogniteCore",
    space="cdf_cdm",
    version="v1",
)


def test_generate_engine_params_from_user_token() -> None:
    global_config.disable_pypi_version_check = True

    client, data_model_id = generate_engine_params_from_user_token(
        user_token="user-token",
        project="project",
        client_name="test-client",
        cluster="api",
        data_model_id=DATA_MODEL_ID,
    )

    assert client.config.client_name == "test-client"
    assert client.config.project == "project"
    assert client.config.base_url == "https://api.cognitedata.com"
    assert client.config.credentials.authorization_header() == (
        "Authorization",
        "Bearer user-token",
    )
    assert data_model_id == DATA_MODEL_ID


def test_engine_from_user_token() -> None:
    global_config.disable_pypi_version_check = True

    engine = Engine.from_user_token(
        user_token="user-token",
        project="project",
        cluster="api",
        data_model_id=DATA_MODEL_ID,
    )

    client = engine._cognite_adapter._cognite_client
    assert client.config.project == "project"
    assert client.config.credentials.authorization_header() == (
        "Authorization",
        "Bearer user-token",
    )


def test_async_engine_from_user_token() -> None:
    global_config.disable_pypi_version_check = True

    engine = AsyncEngine.from_user_token(
        user_token="user-token",
        project="project",
        cluster="api",
        data_model_id=DATA_MODEL_ID,
    )

    client = engine._engine._cognite_adapter._cognite_client
    assert client.config.project == "project"
    assert client.config.credentials.authorization_header() == (
        "Authorization",
        "Bearer user-token",
    )
