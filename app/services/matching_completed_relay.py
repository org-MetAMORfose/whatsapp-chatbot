"""Direct WhatsApp delivery of matching results, with no Redis or outbound messages."""

import asyncio
import logging
from typing import Any

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.domain.whatsapp.matching_patient_template import MatchingPatientTemplate
from app.domain.whatsapp.matching_professional_template import MatchingProfessionalTemplate
from app.domain.whatsapp.template_history import template_history_content
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
    def __init__(self, repository: OutboxRepository, adapter: WhatsAppAdapter) -> None:
        self.repository = repository
        self.adapter = adapter

    async def process_next(self) -> bool:
        item = await asyncio.to_thread(
            self.repository.claim,
            kinds=("matching.completed", "matching.professional.notification"),
            max_attempts=MAX_ATTEMPTS,
        )
        if item is None:
            return False
        try:
            status = item.payload.get("status")
            if item.kind == "matching.professional.notification":
                if status != "matched":
                    raise ValueError("Professional notification requires a matched result")
                self._validate_matched_payload(item.payload)
                professional_template = MatchingProfessionalTemplate(
                    professional_phone=item.payload.get("professional_phone", ""),
                    patient_name=item.payload.get("patient_name", ""),
                    patient_area=item.payload.get("patient_area", ""),
                    patient_phone=item.payload.get("patient_phone", ""),
                )
                await self.adapter.send_template(
                    to=professional_template.professional_phone,
                    name=professional_template.name,
                    language=professional_template.language,
                    body_parameters=professional_template.body_parameters,
                    callback_data=f"{item.id}|{item.attempts}",
                )
                recorded = await asyncio.to_thread(
                    self.repository.record_accepted_whatsapp_template,
                    item,
                    phone_number=professional_template.professional_phone,
                    content=template_history_content(
                        professional_template.name,
                        professional_template.language,
                        professional_template.body_parameters,
                    ),
                )
                if not recorded:
                    raise RuntimeError("Accepted template lost its outbox lease")
            elif item.kind == "matching.completed":
                if status == "matched":
                    self._validate_matched_payload(item.payload)
                    patient_template = MatchingPatientTemplate(
                        patient_phone=item.payload.get("patient_phone", ""),
                        professional_name=item.payload.get("professional_name", ""),
                        professional_area=item.payload.get("professional_area", ""),
                        professional_phone=item.payload.get("professional_phone", ""),
                    )
                    await self.adapter.send_template(
                        to=patient_template.patient_phone,
                        name=patient_template.name,
                        language=patient_template.language,
                        body_parameters=patient_template.body_parameters,
                        callback_data=f"{item.id}|{item.attempts}",
                    )
                    recorded = await asyncio.to_thread(
                        self.repository.record_accepted_whatsapp_template,
                        item,
                        phone_number=patient_template.patient_phone,
                        content=template_history_content(
                            patient_template.name,
                            patient_template.language,
                            patient_template.body_parameters,
                        ),
                    )
                    if not recorded:
                        raise RuntimeError("Accepted template lost its outbox lease")
                elif status not in ("no_capacity", "patient_not_found"):
                    raise ValueError("Unknown matching completion status")
            else:
                raise ValueError("Unknown matching notification kind")
        except Exception as exc:
            logger.error("Matching notification failed: id=%s attempt=%s error=%s", item.id, item.attempts, type(exc).__name__)
            await asyncio.to_thread(self.repository.finish, item, exc, max_attempts=MAX_ATTEMPTS)
        else:
            if status != "matched":
                await asyncio.to_thread(self.repository.finish, item, max_attempts=MAX_ATTEMPTS)
        return True

    @staticmethod
    def _validate_matched_payload(payload: dict[str, Any]) -> None:
        patient_id = positive_id(payload, "patient_id", required=True)
        if patient_id is None:
            raise ValueError("Missing patient_id")
        positive_id(payload, "slot_id")
        positive_id(payload, "cycle_id")

    async def run(self, ctx: AppContext) -> None:
        while not ctx.is_shutting_down():
            if not await self.process_next():
                await asyncio.sleep(0.2)
