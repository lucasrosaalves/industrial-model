import os
from pathlib import Path

from industrial_model import Engine


def generate_engine() -> Engine:
    return Engine.from_config_file(
        Path(f"{os.path.dirname(__file__)}/cognite-sdk-config.yaml")
    )
