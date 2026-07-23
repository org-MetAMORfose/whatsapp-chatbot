"""Tests for application settings helpers."""

from pathlib import Path

import pytest

from app.config import settings


def test_load_google_service_account_credentials_from_json() -> None:
    credentials = settings.load_google_service_account_credentials(
        ' { "type": "service_account", "project_id": "test-project" } '
    )

    assert credentials == {
        "type": "service_account",
        "project_id": "test-project",
    }


def test_load_google_service_account_credentials_from_file_path(tmp_path: Path) -> None:
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text(
        '{"type": "service_account", "client_email": "bot@example.com"}',
        encoding="utf-8",
    )

    credentials = settings.load_google_service_account_credentials(
        str(credentials_file)
    )

    assert credentials == {
        "type": "service_account",
        "client_email": "bot@example.com",
    }


def test_load_google_service_account_credentials_with_missing_file(tmp_path: Path) -> None:
    missing_file = tmp_path / "missing.json"

    with pytest.raises(ValueError, match="does not exist"):
        settings.load_google_service_account_credentials(str(missing_file))


def test_load_google_service_account_credentials_with_invalid_json() -> None:
    with pytest.raises(ValueError, match="contains invalid JSON"):
        settings.load_google_service_account_credentials("{invalid-json")


def test_load_google_service_account_credentials_with_empty_value() -> None:
    with pytest.raises(ValueError, match="must be set"):
        settings.load_google_service_account_credentials("   ")
