"""Development gateway: charges are never paid by themselves; payment arrives by posting the webhook."""
from datetime import UTC, datetime, timedelta

from app.services.pix.gateway import PixCharge, PixChargeStatus, PixRefund


class FakePixGateway:
    async def create_charge(self, *, txid: str, amount_cents: int, expires_seconds: int, payer_name: str | None) -> PixCharge:
        return PixCharge(txid=txid, copia_cola=f"PIX-SIMULADO-{txid}", expires_at=datetime.now(UTC) + timedelta(seconds=expires_seconds))

    async def get_charge(self, txid: str) -> PixChargeStatus:
        return PixChargeStatus(txid=txid, paid=False, e2e_id=None, paid_at=None)

    async def refund(self, *, e2e_id: str, refund_id: str, amount_cents: int) -> PixRefund:
        return PixRefund(refund_id=refund_id, status="DEVOLVIDO")

    async def get_refund(self, *, e2e_id: str, refund_id: str) -> PixRefund:
        return PixRefund(refund_id=refund_id, status="DEVOLVIDO")

    async def cancel_charge(self, txid: str) -> None:
        return None
