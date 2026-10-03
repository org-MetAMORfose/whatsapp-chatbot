"""Independent delivery of professional matching e-mails."""

import asyncio
import logging

from app.context import AppContext
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.email_service import GmailSmtpAdapter, MatchingProfessionalEmail

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
EMAIL_KIND = "matching.professional.email"


class MatchingEmailRelay:
    def __init__(self, repository: OutboxRepository, adapter: GmailSmtpAdapter) -> None:
        self.repository = repository
        self.adapter = adapter

    async def process_next(self) -> bool:
        item = await asyncio.to_thread(
            self.repository.claim,
            kinds=(EMAIL_KIND,),
            max_attempts=MAX_ATTEMPTS,
        )
        if item is None:
            return False

        try:
            if item.payload.get("status") != "matched":
                raise ValueError("Professional e-mail requires a matched result")
            notification = MatchingProfessionalEmail(
                recipient=item.payload.get("professional_email", ""),
                patient_name=item.payload.get("patient_name", ""),
                patient_area=item.payload.get("patient_area", ""),
                patient_phone=item.payload.get("patient_phone", ""),
            )
            await asyncio.to_thread(
                self.adapter.send,
                notification,
                operation_id=item.id,
            )
        except Exception as exc:
            logger.error(
                "Matching e-mail failed: id=%s attempt=%s error=%s",
                item.id,
                item.attempts,
                type(exc).__name__,
            )
            await asyncio.to_thread(
                self.repository.finish,
                item,
                exc,
                max_attempts=MAX_ATTEMPTS,
            )
        else:
            await asyncio.to_thread(
                self.repository.finish,
                item,
                max_attempts=MAX_ATTEMPTS,
            )
        return True

    async def run(self, ctx: AppContext) -> None:
        while not ctx.is_shutting_down():
            if not await self.process_next():
                await asyncio.sleep(1)
