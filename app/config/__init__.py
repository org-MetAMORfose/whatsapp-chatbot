"""Application configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

from .logger import setup_logging


def __get_env_variable(name: str, default: str | None = None) -> str:
    """Helper to retrieve environment variables with optional default."""
    value = os.getenv(name, default)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' is not set and no default provided."
        )
    return value


load_dotenv()
LOG_LEVEL = __get_env_variable("LOG_LEVEL", "INFO")
setup_logging(level=LOG_LEVEL)


REDIS_HOST = __get_env_variable("REDIS_HOST", "localhost")
REDIS_PORT = int(__get_env_variable("REDIS_PORT", "6379"))
REDIS_DB = int(__get_env_variable("REDIS_DB", "0"))
REDIS_USERNAME = __get_env_variable("REDIS_USERNAME", "default")
REDIS_PASSWORD = __get_env_variable("REDIS_PASSWORD", "")
