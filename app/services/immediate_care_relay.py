"""Worker side of immediate care: offers to psychologists, the 5-minute deadline, refunds and the video room.

Every outbox kind is idempotent: state transitions are conditional UPDATEs, plain messages carry a stable
event_id so the dispatcher never sends them twice, and a failed step is retried by the outbox lease.
Money steps get a long retry budget; a refund is only reported to the patient once the bank confirms it.
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
from app.domain.db.delivery_model import OutboxModel
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
from app.services.immediate_payment import confirm_payment
from app.services.pix.gateway import PixGateway, format_reais
from app.services.video_room_service import VideoRoomService

logger = logging.getLogger(__name__)
QUEUE_NODE = "imediato_na_fila"
REFUND_CHECK_INTERVAL = timedelta(seconds=60)
REFUND_DONE = "DEVOLVIDO"
REFUND_FAILED = "NAO_REALIZADO"
# The offer is remembered past its deadline so a late "Aceitar" hears "o prazo acabou" instead of going to the flow.
OFFER_MEMORY_GRACE_SECONDS = 3600

PAID_MESSAGE = "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos."
TIMEOUT_MESSAGE = (
    "Nos últimos 5 minutos nenhum psicólogo ficou disponível. Vou devolver o seu Pix de {amount} automaticamente; "
    "você recebe a confirmação por aqui."
)
REFUNDED_MESSAGE = "Pix de {amount} devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET."
ACCEPTED_PATIENT_MESSAGE = "Um psicólogo aceitou o seu atendimento! Entre na sala de vídeo: {url}\n\nA sessão dura {minutes} minutos e não é gravada."
ACCEPTED_PROFESSIONAL_MESSAGE = "Sala de vídeo do acolhimento: {url}\n\nO paciente é {name}, sessão de {minutes} minutos."
PAYMENT_EXPIRED_MESSAGE = "O Pix expirou e nada foi cobrado. Se ainda quiser, mande RESET e peça de novo."
REFUND_FAILED_MESSAGE = (
    "Não consegui devolver o seu Pix de {amount} automaticamente. A equipe da MetAMORfose vai fazer a devolução manualmente "
    "e te avisa por aqui."
)


def _message_id() -> int:
    return int(hashlib.sha256(uuid4().bytes).hexdigest()[:12], 16)


def _first_name(request: ImmediateRequestModel) -> str:
    name = (request.patient.name or "").strip() if request.patient is not None else ""
    return name.split()[0] if name else "Paciente"


class ImmediateCareRelay:
    KINDS = (
        "immediate.offer.v1",
        "immediate.timeout.v1",
        "immediate.refund.v1",
        "immediate.refund_check.v1",
        "immediate.accepted.v1",
        "immediate.payment_timeout.v1",
        "immediate.cancel_charge.v1",
    )
    # Outbox backoff caps at 5 minutes, so 120 attempts cover roughly nine hours of a bank or video outage.
    MAX_ATTEMPTS = 120
    # Refund status is re-checked every minute for up to an hour before someone has to look at it.
    REFUND_CHECK_LIMIT = 60

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
        self.offer_timeout = timedelta(seconds=offer_timeout_seconds)
        self.room_grace_minutes = room_grace_minutes
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
        self._handlers: dict[str, Callable[[OutboxModel], Awaitable[None]]] = {
            "immediate.offer.v1": self._offer,
            "immediate.timeout.v1": self._timeout,
            "immediate.refund.v1": self._refund,
            "immediate.refund_check.v1": self._refund_check,
            "immediate.accepted.v1": self._accepted,
            "immediate.payment_timeout.v1": self._payment_timeout,
            "immediate.cancel_charge.v1": self._cancel_charge,
        }

    async def process_next(self) -> bool:
        item = await asyncio.to_thread(self.outbox.claim, kinds=self.KINDS, max_attempts=self.MAX_ATTEMPTS)
        if item is None:
            return False
        try:
            handler = self._handlers.get(item.kind)
            if handler is None:
                raise ValueError(f"Unknown immediate care kind: {item.kind}")
            await handler(item)
        except Exception as exc:
            if item.attempts >= self.MAX_ATTEMPTS:
                logger.error("Immediate care step exhausted its retries and needs manual action: id=%s kind=%s", item.id, item.kind)
            else:
                logger.exception("Immediate care step failed: id=%s attempt=%s", item.id, item.attempts)
            await asyncio.to_thread(self.outbox.finish, item, exc, max_attempts=self.MAX_ATTEMPTS)
        else:
            await asyncio.to_thread(self.outbox.finish, item, max_attempts=self.MAX_ATTEMPTS)
        return True

    async def run(self, ctx: AppContext) -> None:
        while not ctx.is_shutting_down():
            if not await self.process_next():
                await asyncio.sleep(0.2)

    @staticmethod
    def _request_id(item: OutboxModel) -> int:
        return int(item.payload["request_id"])

    async def _offer(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        request = self.requests.get(request_id)
        if request is None or request.status != ImmediateStatus.QUEUED.value:
            logger.warning("Immediate offer skipped: request=%s status=%s", request_id, getattr(request, "status", None))
            return
        now = self._now()
        patient_phone = request.patient.phone_number
        # The patient hears back even if every offer below fails; both steps are idempotent.
        await self._send_text(request_id, "offer", patient_phone, PAID_MESSAGE)
        await self.chats.create_context(patient_phone, Channel.WHATSAPP, QUEUE_NODE)
        remaining = max(1, int((request.expires_at - now).total_seconds()))
        # A professional who is also the patient of this request never gets its offer.
        candidates = [
            professional
            for professional in self.professionals.list_available_for_immediate()
            if professional.person_id != request.patient_person_id
        ]
        if not candidates:
            logger.warning("Immediate request %s paid but no psychologist is available", request_id)
        for professional in candidates:
            phone = professional.person.phone_number if professional.person is not None else ""
            try:
                template = ImmediateOfferTemplate(
                    professional_phone=phone,
                    patient_first_name=_first_name(request),
                    duration_minutes=request.duration_minutes,
                    amount_text=amount_text(request.amount_cents),
                )
                await self.whatsapp.send_template(
                    to=template.professional_phone,
                    name=template.name,
                    language=template.language,
                    body_parameters=template.body_parameters,
                    callback_data=None,
                )
                self._record_history(phone, template_history_content(template.name, template.language, template.body_parameters), now)
                await self.offers.mark(phone, Channel.WHATSAPP, request_id, ttl_seconds=remaining + OFFER_MEMORY_GRACE_SECONDS)
            except Exception:
                logger.exception("Immediate offer not delivered to professional %s (%r) for request %s", professional.id, phone, request_id)

    async def _timeout(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        with transaction(self.factory):
            self.requests.expire(request_id)
            request = self.requests.get(request_id)
            if request is None or request.status != ImmediateStatus.EXPIRED.value:
                return
            self.outbox.enqueue(f"immediate:{request_id}:refund", "immediate.refund.v1", {"request_id": request_id})
        patient_phone = request.patient.phone_number
        await self._send_text(request_id, "timeout", patient_phone, TIMEOUT_MESSAGE.format(amount=format_reais(request.amount_cents)))
        await self._leave_flow(patient_phone)

    async def _refund(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        request = self.requests.get(request_id)
        if request is None or await self._resend_refund_outcome(request):
            return
        if not request.pix_e2e_id or not request.pix_txid:
            raise RuntimeError(f"Immediate request {request_id} has no Pix payment to refund")
        refund_id = f"{request.pix_txid}R1"
        try:
            result = await self.pix.refund(e2e_id=request.pix_e2e_id, refund_id=refund_id, amount_cents=request.amount_cents)
        except Exception as error:
            # The PUT may have landed before a transport error, or the bank may refuse the same id twice: read it back
            # before retrying, so one refund is never requested as two.
            logger.warning("Pix refund %s for immediate request %s failed to send (%s); asking the bank", refund_id, request_id, error)
            try:
                result = await self.pix.get_refund(e2e_id=request.pix_e2e_id, refund_id=refund_id)
            except Exception:
                raise error from None
        await self._apply_refund_status(request, result.refund_id or refund_id, result.status, attempt=0)

    async def _resend_refund_outcome(self, request: ImmediateRequestModel) -> bool:
        """Already settled: say so again (the dispatcher dedups by event_id) so a crash never swallows the message."""
        amount = format_reais(request.amount_cents)
        if request.refunded_at is not None:
            await self._send_text(request.id, "refund", request.patient.phone_number, REFUNDED_MESSAGE.format(amount=amount))
            return True
        if request.refund_failed_at is not None:
            await self._send_text(request.id, "refund_failed", request.patient.phone_number, REFUND_FAILED_MESSAGE.format(amount=amount))
            return True
        return False

    async def _refund_check(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        attempt = int(item.payload.get("attempt", 1))
        request = self.requests.get(request_id)
        if request is None or await self._resend_refund_outcome(request):
            return
        if not request.pix_e2e_id or not request.pix_refund_id:
            raise RuntimeError(f"Immediate request {request_id} has no pending refund to check")
        result = await self.pix.get_refund(e2e_id=request.pix_e2e_id, refund_id=request.pix_refund_id)
        await self._apply_refund_status(request, request.pix_refund_id, result.status, attempt=attempt)

    async def _apply_refund_status(self, request: ImmediateRequestModel, refund_id: str, status: str, *, attempt: int) -> None:
        if status == REFUND_DONE:
            self.requests.set_refunded(request.id, refund_id=refund_id, refunded_at=self._now())
            refunded = REFUNDED_MESSAGE.format(amount=format_reais(request.amount_cents))
            await self._send_text(request.id, "refund", request.patient.phone_number, refunded)
            return
        if status == REFUND_FAILED:
            logger.error(
                "Pix refund %s for immediate request %s was not performed by the bank; needs manual action", refund_id, request.id
            )
            await self._refund_failed(request, refund_id)
            return
        # Still processing: remember the id and look again later, without telling the patient anything yet.
        self.requests.set_refund_pending(request.id, refund_id=refund_id)
        if attempt >= self.REFUND_CHECK_LIMIT:
            logger.error(
                "Pix refund %s for immediate request %s is still processing after %s checks; needs manual action", refund_id, request.id, attempt
            )
            await self._refund_failed(request, refund_id)
            return
        next_attempt = attempt + 1
        with transaction(self.factory):
            self.outbox.enqueue(
                f"immediate:{request.id}:refund_check:{next_attempt}",
                "immediate.refund_check.v1",
                {"request_id": request.id, "attempt": next_attempt},
                available_at=self._now() + REFUND_CHECK_INTERVAL,
            )

    async def _refund_failed(self, request: ImmediateRequestModel, refund_id: str) -> None:
        """Record the failure (the panel shows "Estorno falhou") and tell the patient someone will refund by hand."""
        self.requests.set_refund_failed(request.id, refund_id=refund_id, failed_at=self._now())
        message = REFUND_FAILED_MESSAGE.format(amount=format_reais(request.amount_cents))
        await self._send_text(request.id, "refund_failed", request.patient.phone_number, message)

    async def _accepted(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        request = self.requests.get(request_id)
        if request is None or request.status != ImmediateStatus.ACCEPTED.value:
            logger.warning("Immediate accepted step skipped: request=%s status=%s", request_id, getattr(request, "status", None))
            return
        if request.professional is None:
            raise RuntimeError(f"Accepted immediate request {request_id} has no professional")
        patient_url, professional_url = request.patient_room_url, request.professional_room_url
        if not patient_url or not professional_url:
            expires_at = self._now() + timedelta(minutes=request.duration_minutes + self.room_grace_minutes)
            room = await self.video.create_room(name=f"acolhimento-{request_id}-{secrets.token_urlsafe(16)}", expires_at=expires_at)
            self.requests.set_room(
                request_id, room_url=room.room_url, patient_room_url=room.patient_url, professional_room_url=room.professional_url
            )
            patient_url, professional_url = room.patient_url, room.professional_url
        patient_phone = request.patient.phone_number
        professional_phone = request.professional.phone_number
        await self._send_text(
            request_id, "accepted", patient_phone, ACCEPTED_PATIENT_MESSAGE.format(url=patient_url, minutes=request.duration_minutes)
        )
        await self._send_text(
            request_id,
            "accepted",
            professional_phone,
            ACCEPTED_PROFESSIONAL_MESSAGE.format(url=professional_url, name=_first_name(request), minutes=request.duration_minutes),
        )
        # The patient stays in the queue node: any message gets the room link again, then the flow closes. The
        # professional's offer key is kept until its TTL, so a repeated "Aceitar" gets their room link again.

    async def _payment_timeout(self, item: OutboxModel) -> None:
        request_id = self._request_id(item)
        request = self.requests.get(request_id)
        if request is None or not request.pix_txid:
            return
        patient_phone = request.patient.phone_number
        if request.status == ImmediateStatus.CANCELLED.value:
            # Cancelled by the patient (always before the deadline): nothing to say. Cancelled by an earlier attempt of
            # this step (at or after the deadline): resend the notice, which the dispatcher dedups by event_id.
            if request.updated_at is not None and request.updated_at >= request.expires_at:
                await self._send_text(request_id, "payment_timeout", patient_phone, PAYMENT_EXPIRED_MESSAGE)
            return
        if request.status != ImmediateStatus.AWAITING_PAYMENT.value:
            return
        # The webhook may be late or lost: ask the bank before telling the patient nothing was charged.
        charge = await self.pix.get_charge(request.pix_txid)
        if charge.paid and charge.e2e_id:
            with transaction(self.factory):
                confirm_payment(
                    self.requests,
                    self.outbox,
                    txid=request.pix_txid,
                    e2e_id=charge.e2e_id,
                    paid_at=charge.paid_at or self._now(),
                    now=self._now(),
                    offer_timeout=self.offer_timeout,
                )
            logger.info("Late Pix payment found by the bank check for immediate request %s", request_id)
            return
        if not self.requests.cancel(request_id):
            return  # paid or cancelled a moment ago; that path speaks to the patient
        try:
            await self.pix.cancel_charge(request.pix_txid)
        except Exception:
            logger.exception("Could not remove Pix charge %s after the payment deadline", request.pix_txid)
        await self._send_text(request_id, "payment_timeout", patient_phone, PAYMENT_EXPIRED_MESSAGE)
        await self._leave_flow(patient_phone)

    async def _cancel_charge(self, item: OutboxModel) -> None:
        """Remove the charge at the bank after a CANCELAR, outside the message transaction (a lock held across the HTTP
        call froze the worker when the payment deadline fired at the same time)."""
        request_id = self._request_id(item)
        request = self.requests.get(request_id)
        if request is None or request.status != ImmediateStatus.CANCELLED.value or not request.pix_txid:
            return
        await self.pix.cancel_charge(request.pix_txid)

    async def _leave_flow(self, phone: str) -> None:
        """Close the patient's conversation only while it is still inside the immediate care nodes."""
        context = await self.chats.get_context(phone, Channel.WHATSAPP)
        if context is not None and str(context.state).startswith("imediato_"):
            await self.chats.delete_context(phone, Channel.WHATSAPP)

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
