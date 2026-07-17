"""Application configuration loaded from environment variables."""

import json
import os
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

from .logger import setup_logging


def __get_env_variable(name: str, default: str | None = None) -> str:
    """Helper to retrieve environment variables with optional default."""
    value = os.getenv(name, default)
    if value is None:
        raise ValueError(
            f"Environment variable '{name}' is not set and no default provided.")
    return value


def __get_bool_env_variable(name: str, default: str = "0") -> bool:
    value = __get_env_variable(name, default).strip().lower()
    return value in {"1", "true", "yes", "on"}


def __parse_json_object(value: str, error_message: str) -> dict[str, Any]:
    try:
        parsed: object = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(error_message) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            "Environment variable 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' must resolve to a JSON object."
        )

    return cast(dict[str, Any], parsed)


def load_google_service_account_credentials(value: str | None = None) -> dict[str, Any]:
    """Load Google service account credentials from JSON content or a file path."""
    raw_value = (
        __get_env_variable("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS", "")
        if value is None
        else value
    ).strip()

    if not raw_value:
        raise ValueError(
            "Environment variable 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' must be set to a JSON object or a path to a JSON credentials file."
        )

    if raw_value.startswith(("{", "[")):
        return __parse_json_object(
            raw_value,
            "Environment variable 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' contains invalid JSON.",
        )

    credentials_path = Path(raw_value).expanduser()
    try:
        file_content = credentials_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(
            "Environment variable 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' points to a credentials file that does not exist."
        ) from exc
    except OSError as exc:
        raise ValueError(
            "Environment variable 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' points to a credentials file that could not be read."
        ) from exc

    return __parse_json_object(
        file_content,
        "Credentials file configured by 'GOOGLE_SERVICE_ACCOUNT_CREDENTIALS' contains invalid JSON.",
    )


load_dotenv()

LOG_LEVEL = __get_env_variable("LOG_LEVEL", "INFO")
LOKI_URL = __get_env_variable("LOKI_URL", "http://loki:3100")
LOKI_ENABLED = __get_bool_env_variable("LOKI_ENABLED", "false")
setup_logging(level=LOG_LEVEL, loki_url=LOKI_URL, loki_enabled=LOKI_ENABLED)

REDIS_HOST = __get_env_variable("REDIS_HOST", "localhost")
REDIS_PORT = int(__get_env_variable("REDIS_PORT", "6379"))
REDIS_DB = int(__get_env_variable("REDIS_DB", "0"))
REDIS_USERNAME = __get_env_variable("REDIS_USERNAME", "default")
REDIS_PASSWORD = __get_env_variable("REDIS_PASSWORD", "")

TELEGRAM_BOT_TOKEN = __get_env_variable("TELEGRAM_BOT_TOKEN", "")

WHATSAPP_VERIFY_TOKEN = __get_env_variable("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_ACCESS_TOKEN = __get_env_variable("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = __get_env_variable("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_WEBHOOK_PORT = int(
    __get_env_variable("WHATSAPP_WEBHOOK_PORT", "8000"))

USE_TELEGRAM = __get_bool_env_variable("USE_TELEGRAM", "0")
USE_WHATSAPP = __get_bool_env_variable("USE_WHATSAPP", "0")

DATABASE_URL = __get_env_variable("DATABASE_URL", "sqlite:///app.db")

AWS_ACCESS_KEY_ID = __get_env_variable("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = __get_env_variable("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = __get_env_variable("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = __get_env_variable("S3_BUCKET_NAME", "")

GOOGLE_SERVICE_ACCOUNT_CREDENTIALS = load_google_service_account_credentials()
GOOGLE_PATIENTS_SPREADSHEET_URL = __get_env_variable(
    "GOOGLE_PATIENTS_SPREADSHEET_URL", "")
GOOGLE_PROFESSIONALS_SPREADSHEET_URL = __get_env_variable(
    "GOOGLE_PROFESSIONALS_SPREADSHEET_URL", "")
