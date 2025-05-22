import os
from pathlib import Path
from string import Template
from typing import Any

import yaml
from cognite.client import CogniteClient
from dotenv import load_dotenv

from industrial_model import DataModelId, Engine


def generate_config(
    config_file_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    load_dotenv(override=True)
    file_path = Path(
        config_file_path
        or f"{os.path.dirname(__file__)}/cognite-sdk-config.yaml"
    )
    env_sub_template = Template(file_path.read_text())
    file_env_parsed = env_sub_template.substitute(dict(os.environ))

    value = yaml.safe_load(file_env_parsed)

    assert isinstance(value, dict)
    return value


def generate_engine(config_file_path: str | None = None) -> Engine:
    cognite_config = generate_config(config_file_path)
    client = CogniteClient.load(cognite_config["cognite"])

    client.config.timeout = 60
    print(client.config)

    dm_id = DataModelId.model_validate(cognite_config["data_model"])
    return Engine(client, dm_id)
