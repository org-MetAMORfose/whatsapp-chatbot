"""Worker side of immediate care: offers to psychologists, the 5-minute deadline, refunds and the video room.

Every outbox kind is idempotent: state transitions are conditional UPDATEs, plain messages carry a stable
event_id so the dispatcher never sends them twice, and a failed step is retried by the outbox lease.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.channels import Channel
from app.domain.enum.immediate_status import ImmediateStatus
from app.domain.message import Message
from app.domain.whatsapp.immediate_offer_template import ImmediateOfferTemplate, amount_text
from app.domain.whatsapp.template_history import template_history_content
from app.infra.message_queue import MessageQueue
from app.repository.redis.chat_repository import ChatRepository
from app.repository.redis.immediate_offer_repository import ImmediateOfferRepository
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.repository.sql.transaction import transaction
from app.services.pix.gateway import PixGateway, format_reais
from app.services.video_room_service import VideoRoomService

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
QUEUE_NODE = "imediato_na_fila"

PAID_MESSAGE = "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos."
TIMEOUT_MESSAGE = (
    "Nos últimos 5 minutos nenhum psicólogo ficou disponível. Vou devolver o seu Pix de {amount} automaticamente; "
    "você recebe a confirmação por aqui."
)
REFUNDED_MESSAGE = "Pix de {amount} devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET."
ACCEPTED_PATIENT_MESSAGE = "Um psicólogo aceitou o seu atendimento! Entre na sala de vídeo: {url}\n\nA sessão dura {minutes} minutos e não é gravada."
ACCEPTED_PROFESSIONAL_MESSAGE = "Sala de vídeo do acolhimento: {url}\n\nO paciente é {name}, sessão de {minutes} minutos."
PAYMENT_EXPIRED_MESSAGE = "O Pix expirou e nada foi cobrado. Se ainda quiser, mande RESET e peça de novo."


def _message_id() -> int:
    return int(hashlib.sha256(uuid4().bytes).hexdigest()[:12], 16)


def _first_name(request: ImmediateRequestModel) -> str:
    name = (request.patient.name or "").strip() if request.patient is not None else ""
    return name.split()[0] if name else "Paciente"


class ImmediateCareRelay:
    KINDS = ("immediate.offer.v1", "immediate.timeout.v1", "immediate.refund.v1", "immediate.accepted.v1", "immediate.payment_timeout.v1")

    def __init__(
        self,
        outbox: OutboxRepository,
        whatsapp: WhatsAppAdapter,
        outbound: MessageQueue,
        requests: ImmediateRequestRepository,
        professionals: ProfessionalRepository,
        people: PersonRepository,
        offers: ImmediateOfferRepository,
        chats: ChatRepository,
        video: VideoRoomService,
        pix: PixGateway,
        factory: Callable[[], Session],
        *,
        offer_timeout_seconds: int,
        room_grace_minutes: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.outbox = outbox
        self.whatsapp = whatsapp
        self.outbound = outbound
        self.requests = requests
        self.professionals = professionals
        self.people = people
        self.offers = offers
        self.chats = chats
        self.video = video
        self.pix = pix
        self.factory = factory
        self.offer_timeout_seconds = offer_timeout_seconds
        self.room_grace_minutes = room_grace_minutes
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
        self._handlers: dict[str, Callable[[int], Awaitable[None]]] = {
            "immediate.offer.v1": self._offer,
            "immediate.timeout.v1": self._timeout,
            "immediate.refund.v1": self._refund,
            "immediate.accepted.v1": self._accepted,
            "immediate.payment_timeout.v1": self._payment_timeout,
        }

    async def process_next(self) -> bool:
        item = await asyncio.to_thread(self.outbox.claim, kinds=self.KINDS, max_attempts=MAX_ATTEMPTS)
        if item is None:
            return False
        try:
            handler = self._handlers.get(item.kind)
            if handler is None:
                raise ValueError(f"Unknown immediate care kind: {item.kind}")
            await handler(int(item.payload["request_id"]))
        except Exception as exc:
            logger.exception("Immediate care step failed: id=%s attempt=%s", item.id, item.attempts)
            await asyncio.to_thread(self.outbox.finish, item, exc, max_attempts=MAX_ATTEMPTS)
        else:
            await asyncio.to_thread(self.outbox.finish, item, max_attempts=MAX_ATTEMPTS)
        return True

    async def run(self, ctx: AppContext) -> None:
        while not ctx.is_shutting_down():
            if not await self.process_next():
                await asyncio.sleep(0.2)

    async def _offer(self, request_id: int) -> None:
        request = self.requests.get(request_id)
        if request is None or request.status != ImmediateStatus.QUEUED.value:
            logger.warning("Immediate offer skipped: request=%s status=%s", request_id, getattr(request, "status", None))
            return
        now = self._now()
        remaining = max(1, int((request.expires_at - now).total_seconds()))
        candidates = self.professionals.list_available_for_immediate()
        if not candidates:
            logger.warning("Immediate request %s paid but no psychologist is available", request_id)
        for professional in candidates:
            phone = professional.person.phone_number
            template = ImmediateOfferTemplate(
                professional_phone=phone,
                patient_first_name=_first_name(request),
                duration_minutes=request.duration_minutes,
                amount_text=amount_text(request.amount_cents),
            )
            try:
                await self.whatsapp.send_template(
                    to=template.professional_phone,
                    name=template.name,
                    language=template.language,
                    body_parameters=template.body_parameters,
                    callback_data=None,
                )
            except Exception:
                logger.exception("Immediate offer not delivered to %s for request %s", phone, request_id)
                continue
            self._record_history(phone, template_history_content(template.name, template.language, template.body_parameters), now)
            await self.offers.mark(phone, Channel.WHATSAPP, request_id, ttl_seconds=remaining)
        patient_phone = request.patient.phone_number
        await self._send_text(request_id, "offer", patient_phone, PAID_MESSAGE)
        await self.chats.create_context(patient_phone, Channel.WHATSAPP, QUEUE_NODE)

    async def _timeout(self, request_id: int) -> None:
        with transaction(self.factory):
            expired = self.requests.expire(request_id)
            if expired:
                self.outbox.enqueue(f"immediate:{request_id}:refund", "immediate.refund.v1", {"request_id": request_id})
        if not expired:
            return
        request = self.requests.get(request_id)
        if request is None:
            return
        patient_phone = request.patient.phone_number
        await self._send_text(request_id, "timeout", patient_phone, TIMEOUT_MESSAGE.format(amount=format_reais(request.amount_cents)))
        await self.chats.delete_context(patient_phone, Channel.WHATSAPP)

    async def _refund(self, request_id: int) -> None:
        request = self.requests.get(request_id)
        if request is None or request.refunded_at is not None:
            return
        if not request.pix_e2e_id or not request.pix_txid:
            raise RuntimeError(f"Immediate request {request_id} has no Pix payment to refund")
        result = await self.pix.refund(e2e_id=request.pix_e2e_id, refund_id=f"{request.pix_txid}R1", amount_cents=request.amount_cents)
        if result.status == "NAO_REALIZADO":
            raise RuntimeError(f"Pix refund not performed for request {request_id}")
        self.requests.set_refunded(request_id, refund_id=result.refund_id, refunded_at=self._now())
        await self._send_text(request_id, "refund", request.patient.phone_number, REFUNDED_MESSAGE.format(amount=format_reais(request.amount_cents)))

    async def _accepted(self, request_id: int) -> None:
        request = self.requests.get(request_id)
        if request is None or request.status != ImmediateStatus.ACCEPTED.value:
            logger.warning("Immediate accepted step skipped: request=%s status=%s", request_id, getattr(request, "status", None))
            return
        if request.professional is None:
            raise RuntimeError(f"Accepted immediate request {request_id} has no professional")
        url = request.room_url
        if not url:
            expires_at = self._now() + timedelta(minutes=request.duration_minutes + self.room_grace_minutes)
            url = await self.video.create_room(name=f"acolhimento-{request_id}-{secrets.token_hex(3)}", expires_at=expires_at)
            self.requests.set_room(request_id, url)
        patient_phone = request.patient.phone_number
        professional_phone = request.professional.phone_number
        await self._send_text(
            request_id, "accepted", patient_phone, ACCEPTED_PATIENT_MESSAGE.format(url=url, minutes=request.duration_minutes)
        )
        await self._send_text(
            request_id,
            "accepted",
            professional_phone,
            ACCEPTED_PROFESSIONAL_MESSAGE.format(url=url, name=_first_name(request), minutes=request.duration_minutes),
        )
        await self.chats.delete_context(patient_phone, Channel.WHATSAPP)
        await self.offers.clear(professional_phone, Channel.WHATSAPP)

    async def _payment_timeout(self, request_id: int) -> None:
        if not self.requests.cancel(request_id):
            return
        request = self.requests.get(request_id)
        if request is None:
            return
        patient_phone = request.patient.phone_number
        await self._send_text(request_id, "payment_timeout", patient_phone, PAYMENT_EXPIRED_MESSAGE)
        await self.chats.delete_context(patient_phone, Channel.WHATSAPP)

    async def _send_text(self, request_id: int, kind: str, phone: str, content: str) -> None:
        message = Message(
            event_id=f"immediate:{request_id}:{kind}:{phone}",
            message_id=_message_id(),
            channel=Channel.WHATSAPP,
            created_at=self._now(),
            user_id=phone,
            chat_id=phone,
            content=content,
        )
        await self.outbound.publish(message)

    def _record_history(self, phone: str, content: str, now: datetime) -> None:
        with transaction(self.factory):
            person = self.people.get_or_create_person(phone, Channel.WHATSAPP)
            self.people.create_message(MessageHistoryModel(person_id=person.id, created_at=now, content=content, is_from_user=False))
