import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from industrial_model import Engine


@lru_cache
def generate_engine() -> Engine:
    load_dotenv(override=True)
    return Engine.from_config_file(
        Path(f"{os.path.dirname(__file__)}/cognite-sdk-config.yaml")
    )
