"""Professional-side commands of immediate care (DISPONÍVEL, INDISPONÍVEL, Aceitar), handled before the chat flow."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.agent.agent import Response, normalize_text
from app.domain.db.person_model import PersonModel
from app.domain.matching.profile import PSYCHOTHERAPY
from app.domain.message import Message
from app.repository.redis.immediate_offer_repository import ImmediateOfferRepository
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.professional_repository import ProfessionalRepository

AVAILABLE_COMMANDS = frozenset({"disponivel"})
UNAVAILABLE_COMMANDS = frozenset({"indisponivel"})
ACCEPT_COMMANDS = frozenset({"aceitar"})

AVAILABLE_REPLY = "Pronto! Você está disponível para acolhimento imediato. Quando quiser sair, mande INDISPONÍVEL."
UNAVAILABLE_REPLY = "Combinado, você não vai mais receber ofertas de acolhimento imediato. Mande DISPONÍVEL quando quiser voltar."
ONLY_PSYCHOLOGISTS_REPLY = "Por enquanto o acolhimento imediato é só para psicólogos."
NO_OFFER_REPLY = "Não há nenhuma oferta de acolhimento aberta para você agora."
ACCEPTED_REPLY = "Você ficou com o atendimento! Estou criando a sala de vídeo e te mando o link em instantes."
ALREADY_TAKEN_REPLY = "Esse atendimento já foi aceito por outro profissional ou o prazo acabou."


class ImmediateCareInterceptor:
    def __init__(
        self,
        professionals: ProfessionalRepository,
        immediate_requests: ImmediateRequestRepository,
        offers: ImmediateOfferRepository,
        outbox: OutboxRepository,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._professionals = professionals
        self._requests = immediate_requests
        self._offers = offers
        self._outbox = outbox
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))

    async def handle(self, message: Message, person: PersonModel) -> Response | None:
        """Answer a professional command, or None so the message follows the normal flow."""
        command = normalize_text(message.content or "")
        if command not in AVAILABLE_COMMANDS | UNAVAILABLE_COMMANDS | ACCEPT_COMMANDS:
            return None
        professional = self._professionals.get_by_person_id(person.id)
        if professional is None:
            return None
        if command in ACCEPT_COMMANDS:
            return await self._accept(message, person)
        if normalize_text(professional.area) != normalize_text(PSYCHOTHERAPY):
            return Response(content=ONLY_PSYCHOLOGISTS_REPLY)
        available = command in AVAILABLE_COMMANDS
        self._professionals.set_available_for_immediate(person.id, available, now=self._now())
        return Response(content=AVAILABLE_REPLY if available else UNAVAILABLE_REPLY)

    async def _accept(self, message: Message, person: PersonModel) -> Response:
        request_id = await self._offers.get(message.user_id, message.channel)
        if request_id is None:
            return Response(content=NO_OFFER_REPLY)
        await self._offers.clear(message.user_id, message.channel)
        if not self._requests.accept(request_id, professional_person_id=person.id, now=self._now()):
            return Response(content=ALREADY_TAKEN_REPLY)
        self._outbox.enqueue(f"immediate:{request_id}:accepted", "immediate.accepted.v1", {"request_id": request_id})
        return Response(content=ACCEPTED_REPLY)
