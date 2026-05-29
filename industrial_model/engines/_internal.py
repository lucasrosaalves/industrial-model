import os
from collections.abc import Callable
from pathlib import Path
from string import Template

import yaml
from cognite.client import ClientConfig, CogniteClient
from cognite.client.credentials import Token

from industrial_model.config import DataModelId

UserToken = str | Callable[[], str]


def generate_engine_params(
    config_file: str | Path,
) -> tuple[CogniteClient, DataModelId]:
    file_path = Path(config_file) if isinstance(config_file, str) else config_file

    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file {file_path} does not exist")

    env_sub_template = Template(file_path.read_text())
    file_env_parsed = env_sub_template.substitute(dict(os.environ))

    engine_config = yaml.safe_load(file_env_parsed)
    if not isinstance(engine_config, dict):
        raise ValueError("Configuration file must contain a dictionary")
    if "cognite" not in engine_config:
        raise ValueError("Configuration must contain 'cognite' section")
    if "data_model" not in engine_config:
        raise ValueError("Configuration must contain 'data_model' section")

    client = CogniteClient.load(engine_config["cognite"])
    dm_id = DataModelId.model_validate(engine_config["data_model"])
    return client, dm_id


def generate_engine_params_from_user_token(
    *,
    user_token: UserToken,
    project: str,
    data_model_id: DataModelId | dict[str, str],
    client_name: str = "industrial-model",
    base_url: str | None = None,
    cluster: str | None = None,
) -> tuple[CogniteClient, DataModelId]:
    client_config = ClientConfig(
        client_name=client_name,
        project=project,
        credentials=Token(user_token),
        base_url=base_url,
        cluster=cluster,
    )
    return CogniteClient(client_config), DataModelId.model_validate(data_model_id)
