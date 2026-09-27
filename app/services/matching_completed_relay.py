"""Direct WhatsApp delivery of matching results, with no Redis or outbound messages."""
import asyncio
import logging
from typing import Any

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.repository.sql.matching_notification_repository import MatchingNotificationRepository
from app.repository.sql.outbox_repository import OutboxRepository

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def positive_id(payload: dict[str, Any], key: str, *, required: bool = False) -> int | None:
    if key not in payload and not required:
        return None
    value = payload.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(f"Invalid matching {key}")
    return int(value)


class MatchingCompletedRelay:
    def __init__(self, repository: OutboxRepository, notifications: MatchingNotificationRepository, adapter: WhatsAppAdapter) -> None:
        self.repository = repository
        self.notifications = notifications
        self.adapter = adapter

    async def process_next(self) -> bool:
        item = await asyncio.to_thread(self.repository.claim, kinds=("matching.completed",), max_attempts=MAX_ATTEMPTS)
        if item is None:
            return False
        try:
            status = item.payload.get("status")
            if status == "matched":
                patient_id = positive_id(item.payload, "patient_id", required=True)
                if patient_id is None:
                    raise ValueError("Missing patient_id")
                template = await asyncio.to_thread(self.notifications.resolve, patient_id,
                    slot_id=positive_id(item.payload, "slot_id"), cycle_id=positive_id(item.payload, "cycle_id"))
                await self.adapter.send_template(to=template.patient_phone, name=template.name,
                    language=template.language, body_parameters=template.body_parameters)
            elif status not in ("no_capacity", "patient_not_found"):
                raise ValueError("Unknown matching completion status")
        except Exception as exc:
            logger.error("Matching notification failed: id=%s attempt=%s error=%s", item.id, item.attempts, type(exc).__name__)
            await asyncio.to_thread(self.repository.finish, item, exc, max_attempts=MAX_ATTEMPTS)
        else:
            # Never mark success before WhatsApp confirms the request. A DB failure
            # here leaves the lease recoverable; it must not masquerade as success.
            await asyncio.to_thread(self.repository.finish, item, max_attempts=MAX_ATTEMPTS)
        return True

    async def run(self, ctx: AppContext) -> None:
        while not ctx.is_shutting_down():
            if not await self.process_next():
                await asyncio.sleep(0.2)
