"""Banco do Brasil Pix API v2 (cob, pix/devolucao, webhook) with mTLS and a cached OAuth token.

Paths follow the Bacen Pix API standard as exposed by BB; confirm base URLs and the
`gw-dev-app-key` query parameter against the BB developer portal for each environment.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from app.services.pix import brcode
from app.services.pix.gateway import PixCharge, PixChargeStatus, PixRefund, format_amount

SCOPE = "cob.read cob.write pix.read pix.write webhook.read webhook.write"
PAYER_REQUEST = "Acolhimento imediato MetAMORfose"
TOKEN_SAFETY_SECONDS = 60


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class BancoDoBrasilPixGateway:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        dev_app_key: str,
        cert_path: str,
        key_path: str,
        chave: str,
        base_url: str,
        oauth_url: str,
        merchant_name: str = "METAMORFOSE",
        merchant_city: str = "SAO PAULO",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._dev_app_key = dev_app_key
        self._cert: tuple[str, str] | None = (cert_path, key_path) if cert_path else None
        self._chave = chave
        self._base_url = base_url.rstrip("/")
        self._oauth_url = oauth_url
        self._merchant_name = merchant_name
        self._merchant_city = merchant_city
        self._transport = transport
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def _client(self) -> httpx.AsyncClient:
        if self._cert is None:
            return httpx.AsyncClient(timeout=30.0, transport=self._transport)
        return httpx.AsyncClient(timeout=30.0, transport=self._transport, cert=self._cert)

    async def _token(self) -> str:
        if self._access_token is not None and time.monotonic() < self._token_expires_at - TOKEN_SAFETY_SECONDS:
            return self._access_token
        async with self._client() as client:
            response = await client.post(
                self._oauth_url,
                data={"grant_type": "client_credentials", "scope": SCOPE},
                auth=(self._client_id, self._client_secret),
            )
        response.raise_for_status()
        body = response.json()
        self._access_token = str(body["access_token"])
        self._token_expires_at = time.monotonic() + float(body.get("expires_in", 600))
        return self._access_token

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._token()
        async with self._client() as client:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                params={"gw-dev-app-key": self._dev_app_key},
                headers={"Authorization": f"Bearer {token}"},
                json=json,
            )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {}
        return cast(dict[str, Any], response.json())

    async def create_charge(self, *, txid: str, amount_cents: int, expires_seconds: int, payer_name: str | None) -> PixCharge:
        body = await self._request(
            "PUT",
            f"/cob/{txid}",
            json={
                "calendario": {"expiracao": expires_seconds},
                "valor": {"original": format_amount(amount_cents)},
                "chave": self._chave,
                "solicitacaoPagador": PAYER_REQUEST,
            },
        )
        copia_cola = body.get("pixCopiaECola")
        if not isinstance(copia_cola, str) or not copia_cola:
            copia_cola = brcode.from_location(
                location=str(body["location"]), merchant_name=self._merchant_name, merchant_city=self._merchant_city
            )
        raw_calendario = body.get("calendario")
        calendario: dict[str, Any] = raw_calendario if isinstance(raw_calendario, dict) else {}
        created_at = _parse_datetime(calendario.get("criacao")) or datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=int(calendario.get("expiracao", expires_seconds)))
        return PixCharge(txid=str(body.get("txid", txid)), copia_cola=copia_cola, expires_at=expires_at)

    async def get_charge(self, txid: str) -> PixChargeStatus:
        body = await self._request("GET", f"/cob/{txid}")
        payments = body.get("pix") if isinstance(body.get("pix"), list) else []
        if body.get("status") == "CONCLUIDA" and payments:
            first = payments[0]
            return PixChargeStatus(txid=txid, paid=True, e2e_id=first.get("endToEndId"), paid_at=_parse_datetime(first.get("horario")))
        return PixChargeStatus(txid=txid, paid=False, e2e_id=None, paid_at=None)

    async def refund(self, *, e2e_id: str, refund_id: str, amount_cents: int) -> PixRefund:
        body = await self._request("PUT", f"/pix/{e2e_id}/devolucao/{refund_id}", json={"valor": format_amount(amount_cents)})
        return PixRefund(refund_id=str(body.get("id", refund_id)), status=str(body.get("status", "EM_PROCESSAMENTO")))

    async def get_refund(self, *, e2e_id: str, refund_id: str) -> PixRefund:
        body = await self._request("GET", f"/pix/{e2e_id}/devolucao/{refund_id}")
        return PixRefund(refund_id=str(body.get("id", refund_id)), status=str(body.get("status", "EM_PROCESSAMENTO")))

    async def cancel_charge(self, txid: str) -> None:
        """Remove an unpaid charge so a late payment is refused by the bank."""
        await self._request("PATCH", f"/cob/{txid}", json={"status": "REMOVIDA_PELO_USUARIO_RECEBEDOR"})

    async def register_webhook(self, url: str) -> None:
        await self._request("PUT", f"/webhook/{self._chave}", json={"webhookUrl": url})
