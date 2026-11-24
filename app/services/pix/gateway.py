"""Gateway protocol for Pix charges plus money formatting shared by the chatbot."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import app.config.settings as settings


@dataclass(frozen=True)
class PixCharge:
    txid: str
    copia_cola: str
    expires_at: datetime


@dataclass(frozen=True)
class PixChargeStatus:
    txid: str
    paid: bool
    e2e_id: str | None
    paid_at: datetime | None


@dataclass(frozen=True)
class PixRefund:
    refund_id: str
    status: str  # "EM_PROCESSAMENTO" | "DEVOLVIDO" | "NAO_REALIZADO"


class PixGateway(Protocol):
    async def create_charge(self, *, txid: str, amount_cents: int, expires_seconds: int, payer_name: str | None) -> PixCharge: ...

    async def get_charge(self, txid: str) -> PixChargeStatus: ...

    async def refund(self, *, e2e_id: str, refund_id: str, amount_cents: int) -> PixRefund: ...

    async def get_refund(self, *, e2e_id: str, refund_id: str) -> PixRefund: ...

    async def cancel_charge(self, txid: str) -> None: ...


def format_amount(cents: int) -> str:
    """Bank format: 6000 -> "60.00"."""
    reais, centavos = divmod(cents, 100)
    return f"{reais}.{centavos:02d}"


def format_reais(cents: int) -> str:
    """Message format: 6000 -> "R$ 60,00"; 123456 -> "R$ 1.234,56"."""
    reais, centavos = divmod(cents, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{centavos:02d}"


def pix_gateway_from_settings() -> PixGateway:
    from app.services.pix.banco_do_brasil import BancoDoBrasilPixGateway
    from app.services.pix.fake import FakePixGateway

    provider = settings.PIX_PROVIDER.strip().lower()
    if provider == "fake":
        # Never reaches a real patient: with the switch on, a fake provider keeps the feature closed
        # (app.services.immediate_care_config.configuration_problems).
        return FakePixGateway()
    if provider == "bb":
        return BancoDoBrasilPixGateway(
            client_id=settings.BB_PIX_CLIENT_ID,
            client_secret=settings.BB_PIX_CLIENT_SECRET,
            dev_app_key=settings.BB_PIX_DEV_APP_KEY,
            cert_path=settings.BB_PIX_CERT_PATH,
            key_path=settings.BB_PIX_KEY_PATH,
            chave=settings.BB_PIX_CHAVE,
            base_url=settings.BB_PIX_BASE_URL,
            oauth_url=settings.BB_PIX_OAUTH_URL,
        )
    raise ValueError(f"PIX_PROVIDER desconhecido: {settings.PIX_PROVIDER!r} (use 'fake' ou 'bb')")
