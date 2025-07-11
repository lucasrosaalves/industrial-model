import os
from pathlib import Path
from string import Template

import yaml
from cognite.client import CogniteClient

from industrial_model.config import DataModelId


def generate_engine_params(
    config_file: str | Path,
) -> tuple[CogniteClient, DataModelId]:
    file_path = Path(config_file) if isinstance(config_file, str) else config_file

    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file {file_path} does not exist")

    env_sub_template = Template(file_path.read_text())
    file_env_parsed = env_sub_template.substitute(dict(os.environ))

    engine_config = yaml.safe_load(file_env_parsed)
    assert isinstance(
        engine_config, dict
    ), "Configuration file must contain a dictionary"
    assert "cognite" in engine_config, "Configuration must contain 'cognite' section"
    assert (
        "data_model" in engine_config
    ), "Configuration must contain 'data_model' section"

    client = CogniteClient.load(engine_config["cognite"])
    dm_id = DataModelId.model_validate(engine_config["data_model"])
    return client, dm_id
