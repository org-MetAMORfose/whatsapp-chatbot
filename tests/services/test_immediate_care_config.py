import logging

import pytest

import app.config.settings as settings
from app.services.immediate_care_config import configuration_problems, immediate_care_enabled, log_configuration

COMPLETE = {
    "IMMEDIATE_CARE_ENABLED": True,
    "IMMEDIATE_ALLOW_FAKE": False,
    "PIX_PROVIDER": "bb",
    "BB_PIX_CLIENT_ID": "id",
    "BB_PIX_CLIENT_SECRET": "secret",
    "BB_PIX_DEV_APP_KEY": "devkey",
    "BB_PIX_CERT_PATH": "/app/secrets/bb-pix.crt",
    "BB_PIX_KEY_PATH": "/app/secrets/bb-pix.key",
    "BB_PIX_CHAVE": "chave@bb",
    "PIX_WEBHOOK_TOKEN": "token",
    "DAILY_API_KEY": "daily",
    "WHATSAPP_APP_SECRET": "app-secret",
    "WHATSAPP_GRAPH_URL": "https://graph.facebook.com",
    "CHATBOT_API_KEY": "uma-chave-nova-que-nunca-foi-publicada",
    "IMMEDIATE_PRICES_CENTS": {10: 3000, 20: 5000, 40: 10000, 60: 15000},
}


@pytest.fixture
def complete(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in COMPLETE.items():
        monkeypatch.setattr(settings, name, value)
    return monkeypatch


def test_complete_production_configuration_opens_the_feature(complete: pytest.MonkeyPatch) -> None:
    assert configuration_problems() == []
    assert immediate_care_enabled()


def test_switch_off_is_closed_and_reports_nothing(complete: pytest.MonkeyPatch) -> None:
    complete.setattr(settings, "IMMEDIATE_CARE_ENABLED", False)
    complete.setattr(settings, "DAILY_API_KEY", "")
    assert configuration_problems() == []
    assert not immediate_care_enabled()


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("PIX_PROVIDER", "fake", "PIX_PROVIDER=bb"),
        ("BB_PIX_CERT_PATH", "", "BB_PIX_CERT_PATH"),
        ("PIX_WEBHOOK_TOKEN", "", "PIX_WEBHOOK_TOKEN"),
        ("DAILY_API_KEY", "", "DAILY_API_KEY"),
        ("WHATSAPP_APP_SECRET", "", "WHATSAPP_APP_SECRET"),
        ("WHATSAPP_GRAPH_URL", "http://localhost:8099", "WHATSAPP_GRAPH_URL"),
        ("CHATBOT_API_KEY", "", "CHATBOT_API_KEY"),
        ("IMMEDIATE_PRICES_CENTS", {}, "IMMEDIATE_PRICES"),
    ],
)
def test_each_missing_piece_keeps_the_feature_closed(complete: pytest.MonkeyPatch, name: str, value: object, expected: str) -> None:
    complete.setattr(settings, name, value)
    assert not immediate_care_enabled()
    assert any(expected in problem for problem in configuration_problems())


def test_problems_are_logged_as_critical_instead_of_crashing(complete: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    complete.setattr(settings, "WHATSAPP_APP_SECRET", "")
    with caplog.at_level(logging.INFO):
        log_configuration()
    assert [record.levelno for record in caplog.records] == [logging.CRITICAL]
    assert "WHATSAPP_APP_SECRET" in caplog.records[0].getMessage()


def test_a_published_api_key_keeps_the_feature_closed(complete: pytest.MonkeyPatch) -> None:
    import hashlib

    import app.services.immediate_care_config as config

    complete.setattr(config, "PUBLISHED_API_KEY_HASHES", frozenset({hashlib.sha256(b"chave-vazada").hexdigest()}))
    complete.setattr(settings, "CHATBOT_API_KEY", "chave-vazada")
    assert not immediate_care_enabled()
    assert any("publicada" in problem for problem in configuration_problems())
