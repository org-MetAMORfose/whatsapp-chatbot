"""Pix payment notifications (Bacen webhook format) that move immediate requests into the queue.

The URL carries a secret token; BB also calls `{url}/pix`, so both paths are served. The token alone is not trusted
with money: the event must name a known charge with the right amount and, with the real bank, the charge is read
back from the bank before the request is queued. Duplicate or unknown events are acknowledged and ignored, so the
bank never retries forever.
"""
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.transaction import transaction
from app.services.immediate_payment import confirm_payment
from app.services.pix.gateway import PixChargeStatus

logger = logging.getLogger(__name__)
WEBHOOK_TOKEN_IN_PATH = re.compile(r"(/pix/webhook/)[^/\s\"?]+")


class WebhookTokenLogFilter(logging.Filter):
    """Keeps the webhook secret out of access logs and other log lines that print the URL."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = WEBHOOK_TOKEN_IN_PATH.sub(r"\1***", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(WEBHOOK_TOKEN_IN_PATH.sub(r"\1***", arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


class PixEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    txid: str = Field(min_length=1, max_length=35)
    end_to_end_id: str = Field(alias="endToEndId", min_length=1)
    valor: str
    horario: datetime


class PixWebhookBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pix: list[PixEvent]


def _cents(valor: str) -> int | None:
    try:
        return int((Decimal(valor.strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


class PixWebhookController:
    def __init__(
        self,
        factory: Callable[[], Session],
        requests: ImmediateRequestRepository,
        outbox: OutboxRepository,
        *,
        token: str,
        offer_timeout_seconds: int,
        verify_with_bank: Callable[[str], Awaitable[PixChargeStatus]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._factory = factory
        self._requests = requests
        self._outbox = outbox
        self._token = token
        self._offer_timeout = timedelta(seconds=offer_timeout_seconds)
        self._verify = verify_with_bank
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
        self.router = APIRouter()
        self.router.add_api_route("/pix/webhook/{token}", self.receive, methods=["POST"])
        self.router.add_api_route("/pix/webhook/{token}/pix", self.receive, methods=["POST"])

    async def receive(self, token: str, body: PixWebhookBody) -> dict[str, int]:
        if not self._token or not secrets.compare_digest(token.encode(), self._token.encode()):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        queued = 0
        for event in body.pix:
            if await self._confirm(event):
                queued += 1
        return {"received": len(body.pix), "queued": queued}

    async def _confirm(self, event: PixEvent) -> bool:
        known = self._requests.get_by_txid(event.txid)
        if known is None:
            logger.info("Pix event ignored (unknown txid): txid=%s", event.txid)
            return False
        cents = _cents(event.valor)
        if cents != known.amount_cents:
            logger.error("Pix event ignored: amount %r does not match request %s (%s cents)", event.valor, known.id, known.amount_cents)
            return False
        e2e_id = event.end_to_end_id
        paid_at = event.horario if event.horario.tzinfo else event.horario.replace(tzinfo=UTC)
        if self._verify is not None:
            charge = await self._verify(event.txid)
            if not charge.paid:
                logger.error("Pix event ignored: the bank does not report charge %s as paid (request %s)", event.txid, known.id)
                return False
            e2e_id = charge.e2e_id or e2e_id
            paid_at = charge.paid_at or paid_at
        with transaction(self._factory):
            request = confirm_payment(
                self._requests,
                self._outbox,
                txid=event.txid,
                e2e_id=e2e_id,
                paid_at=paid_at,
                now=self._now(),
                offer_timeout=self._offer_timeout,
            )
        if request is None:
            logger.info("Pix event ignored (already handled): txid=%s", event.txid)
            return False
        logger.info("Pix confirmed for immediate request %s; offer and timeout queued", request.id)
        return True
