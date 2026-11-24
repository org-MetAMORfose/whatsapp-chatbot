from datetime import UTC, datetime

import pytest

import app.config.settings as settings
from app.services.pix.banco_do_brasil import BancoDoBrasilPixGateway
from app.services.pix.fake import FakePixGateway
from app.services.pix.gateway import format_amount, format_reais, pix_gateway_from_settings


@pytest.mark.asyncio
async def test_fake_gateway_contract():
    gateway = FakePixGateway()
    charge = await gateway.create_charge(txid="t" * 32, amount_cents=6000, expires_seconds=1800, payer_name="Maria")
    assert charge.txid == "t" * 32
    assert charge.copia_cola == "PIX-SIMULADO-" + "t" * 32
    assert charge.expires_at > datetime.now(UTC)
    status = await gateway.get_charge("t" * 32)
    assert status.txid == "t" * 32 and status.paid is False and status.e2e_id is None and status.paid_at is None
    refund = await gateway.refund(e2e_id="E1", refund_id="t" * 32 + "R1", amount_cents=6000)
    assert refund.refund_id == "t" * 32 + "R1" and refund.status == "DEVOLVIDO"


def test_format_amount_and_reais():
    assert format_amount(6000) == "60.00"
    assert format_amount(9050) == "90.50"
    assert format_amount(5) == "0.05"
    assert format_reais(6000) == "R$ 60,00"
    assert format_reais(9050) == "R$ 90,50"
    assert format_reais(123456) == "R$ 1.234,56"


def test_from_settings_selects_provider(monkeypatch):
    monkeypatch.setattr(settings, "PIX_PROVIDER", "fake")
    assert isinstance(pix_gateway_from_settings(), FakePixGateway)
    monkeypatch.setattr(settings, "PIX_PROVIDER", "bb")
    monkeypatch.setattr(settings, "BB_PIX_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "BB_PIX_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "BB_PIX_DEV_APP_KEY", "key")
    monkeypatch.setattr(settings, "BB_PIX_CHAVE", "chave@bb")
    assert isinstance(pix_gateway_from_settings(), BancoDoBrasilPixGateway)
    monkeypatch.setattr(settings, "PIX_PROVIDER", "outro")
    with pytest.raises(ValueError):
        pix_gateway_from_settings()


@pytest.mark.asyncio
async def test_fake_gateway_refund_check_and_cancel():
    gateway = FakePixGateway()
    refund = await gateway.get_refund(e2e_id="E1", refund_id="t" * 32 + "R1")
    assert refund.status == "DEVOLVIDO" and refund.refund_id == "t" * 32 + "R1"
    await gateway.cancel_charge("t" * 32)


def test_switch_on_with_the_fake_pix_keeps_the_feature_closed(monkeypatch):
    from app.services.immediate_care_config import configuration_problems, immediate_care_enabled

    monkeypatch.setattr(settings, "PIX_PROVIDER", "fake")
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", False)
    assert not immediate_care_enabled()
    assert any("PIX_PROVIDER=bb" in problem for problem in configuration_problems())
    # The factory itself never crashes the API or the worker: the closed gate keeps the fake away from patients.
    assert isinstance(pix_gateway_from_settings(), FakePixGateway)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", True)
    assert immediate_care_enabled()
