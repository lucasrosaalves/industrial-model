import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from industrial_model import AsyncEngine, Engine


@lru_cache
def generate_engine() -> Engine:
    load_dotenv(override=True)
    return Engine.from_config_file(
        Path(f"{os.path.dirname(__file__)}/cognite-sdk-config.yaml")
    )


@lru_cache
def generate_async_engine() -> AsyncEngine:
    load_dotenv(override=True)
    return AsyncEngine.from_config_file(
        Path(f"{os.path.dirname(__file__)}/cognite-sdk-config.yaml")
    )
