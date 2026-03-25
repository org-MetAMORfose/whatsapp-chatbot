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


def __get_bool_env_variable(name: str, default: str = "0") -> bool:
    value = __get_env_variable(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


load_dotenv()

LOG_LEVEL = __get_env_variable("LOG_LEVEL", "INFO")
setup_logging(level=LOG_LEVEL)

REDIS_HOST = __get_env_variable("REDIS_HOST", "localhost")
REDIS_PORT = int(__get_env_variable("REDIS_PORT", "6379"))
REDIS_DB = int(__get_env_variable("REDIS_DB", "0"))
REDIS_USERNAME = __get_env_variable("REDIS_USERNAME", "default")
REDIS_PASSWORD = __get_env_variable("REDIS_PASSWORD", "")

TELEGRAM_BOT_TOKEN = __get_env_variable("TELEGRAM_BOT_TOKEN", "")

WHATSAPP_VERIFY_TOKEN = __get_env_variable("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = __get_env_variable("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = __get_env_variable("WHATSAPP_PHONE_NUMBER_ID", "")

USE_TELEGRAM = __get_bool_env_variable("USE_TELEGRAM", "1")
USE_WHATSAPP = __get_bool_env_variable("USE_WHATSAPP", "0")