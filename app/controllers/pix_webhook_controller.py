"""Pix payment notifications (Bacen webhook format) that move immediate requests into the queue.

The URL carries a secret token; BB also calls `{url}/pix`, so both paths are served.
Duplicate or unknown events are acknowledged and ignored, so the bank never retries forever.
"""
import logging
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.transaction import transaction
from app.services.immediate_payment import confirm_payment

logger = logging.getLogger(__name__)


class PixEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    txid: str = Field(min_length=1, max_length=35)
    end_to_end_id: str = Field(alias="endToEndId", min_length=1)
    valor: str
    horario: datetime


class PixWebhookBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pix: list[PixEvent]


class PixWebhookController:
    def __init__(
        self,
        factory: Callable[[], Session],
        requests: ImmediateRequestRepository,
        outbox: OutboxRepository,
        *,
        token: str,
        offer_timeout_seconds: int,
    ) -> None:
        self._factory = factory
        self._requests = requests
        self._outbox = outbox
        self._token = token
        self._offer_timeout = timedelta(seconds=offer_timeout_seconds)
        self.router = APIRouter()
        self.router.add_api_route("/pix/webhook/{token}", self.receive, methods=["POST"])
        self.router.add_api_route("/pix/webhook/{token}/pix", self.receive, methods=["POST"])

    def receive(self, token: str, body: PixWebhookBody) -> dict[str, int]:
        if not self._token or not secrets.compare_digest(token, self._token):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        queued = 0
        for event in body.pix:
            paid_at = event.horario if event.horario.tzinfo else event.horario.replace(tzinfo=UTC)
            with transaction(self._factory):
                request = confirm_payment(
                    self._requests, self._outbox, txid=event.txid, e2e_id=event.end_to_end_id, paid_at=paid_at, offer_timeout=self._offer_timeout
                )
            if request is None:
                logger.info("Pix event ignored (unknown txid or already handled): txid=%s", event.txid)
                continue
            queued += 1
            logger.info("Pix confirmed for immediate request %s; offer and timeout queued", request.id)
        return {"received": len(body.pix), "queued": queued}
