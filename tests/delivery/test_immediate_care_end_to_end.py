"""Immediate care end to end on a disposable, fully migrated PostgreSQL plus the test Redis.

Real pieces: published flow, agent + actions, repositories, outbox, webhook controller, interceptor, relay,
fake Pix and fake video room. Mocked edges: the WhatsApp HTTP adapter and the outbound queue.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.config.settings as settings
from app.agent.agent import AgentWorker, Response
from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.controllers.pix_webhook_controller import PixEvent, PixWebhookBody, PixWebhookController
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.enum.immediate_status import ImmediateStatus
from app.domain.message import Message
from app.repository.redis.chat_repository import ChatRepository
from app.repository.redis.chatbot_flow_cache import StaticFlowProvider
from app.repository.redis.immediate_offer_repository import ImmediateOfferRepository
from app.repository.redis.patient_stage_repository import PatientStageRepository
from app.repository.redis.professional_stage_repository import ProfessionalStageRepository
from app.repository.redis.sheets_stage_repository import SheetsStageRepository
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.repository.sql.faq_session_repository import FaqSessionRepository
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.repository.sql.transaction import transaction
from app.services.immediate_care_interceptor import ACCEPTED_REPLY, ALREADY_YOURS_REPLY, ImmediateCareInterceptor
from app.services.immediate_care_relay import ImmediateCareRelay
from app.services.pix.fake import FakePixGateway
from app.services.video_room_service import FakeVideoRoomService

PATIENT = "5511999990001"
PSYCHOLOGIST = "5511999990002"
TOKEN = "segredo-e2e"


@pytest.fixture(scope="module")
def migrated_url() -> Iterator[str]:
    url = os.environ.get("DELIVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DELIVERY_TEST_DATABASE_URL to an isolated PostgreSQL")
    name = "immediate_e2e_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    try:
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": test_url.replace("%", "%%"), "PYTHON_DOTENV_DISABLED": "1"},
            capture_output=True,
        )
        yield test_url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db(migrated_url: str) -> Iterator[Callable[[], Session]]:
    engine = create_engine(migrated_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE person, outbox, immediate_request RESTART IDENTITY CASCADE"))
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()


class World:
    def __init__(self, db: Callable[[], Session], redis_client: object) -> None:
        self.db = db
        self.people = PersonRepository(db)
        self.professionals = ProfessionalRepository(db)
        self.outbox = OutboxRepository(db)
        self.requests = ImmediateRequestRepository(db)
        self.chats = ChatRepository(redis_client)  # type: ignore[arg-type]
        self.offers = ImmediateOfferRepository(redis_client)  # type: ignore[arg-type]
        self.pix = FakePixGateway()
        _version, flow = ChatFlowRepository(db).load()
        self.agent = AgentWorker(
            ctx=AppContext(),
            inbound=MagicMock(),
            outbound=MagicMock(),
            chat_repository=self.chats,
            professional_repository=self.professionals,
            professional_stage_repository=ProfessionalStageRepository(redis_client),  # type: ignore[arg-type]
            person_repository=self.people,
            patient_repository=PatientRepository(db),
            patient_stage_repository=PatientStageRepository(redis_client),  # type: ignore[arg-type]
            outbox_repository=self.outbox,
            faq_knowledge_repository=FaqKnowledgeRepository(db),
            faq_session_repository=FaqSessionRepository(db),
            flow_provider=StaticFlowProvider(flow),
            sheets_stage_repository=SheetsStageRepository(redis_client),  # type: ignore[arg-type]
            immediate_requests=self.requests,
            pix_gateway=self.pix,
        )
        self.whatsapp = MagicMock(spec=WhatsAppAdapter)
        self.whatsapp.send_template = AsyncMock(return_value="wamid.offer")
        self.outbound = MagicMock()
        self.outbound.publish = AsyncMock()
        self.relay = ImmediateCareRelay(
            self.outbox,
            self.whatsapp,
            self.outbound,
            self.requests,
            self.professionals,
            self.people,
            self.offers,
            self.chats,
            FakeVideoRoomService(),
            self.pix,
            db,
            offer_timeout_seconds=300,
            room_grace_minutes=15,
        )
        self.interceptor = ImmediateCareInterceptor(self.professionals, self.requests, self.offers, self.outbox)
        self.clock = datetime.now(UTC)
        self.webhook = PixWebhookController(
            db, self.requests, self.outbox, token=TOKEN, offer_timeout_seconds=300, now=lambda: self.clock
        )

    def seed_psychologist(self, *, available: bool) -> PersonModel:
        with self.db() as session:
            person = PersonModel(phone_number=PSYCHOLOGIST, channel=Channel.WHATSAPP, name="Dra. Ana", created_at=datetime.utcnow())
            session.add(person)
            session.flush()
            session.add(
                ProfessionalModel(
                    person_id=person.id,
                    area="Psicoterapia",
                    professional_register="CRP-1",
                    register_type="CRP",
                    available_for_immediate=available,
                    immediate_approved_at=datetime.now(UTC),
                    created_at=datetime.utcnow(),
                )
            )
            session.commit()
            session.refresh(person)
            return person

    async def say(self, phone: str, content: str) -> Response:
        with transaction(self.db):
            self.people.get_or_create_person(phone, Channel.WHATSAPP)
            return await self.agent._process_message(message(phone, content))

    async def professional_says(self, content: str) -> Response | None:
        person = self.people.get_by_phone_number_and_channel(PSYCHOLOGIST, Channel.WHATSAPP)
        assert person is not None
        with transaction(self.db):
            return await self.interceptor.handle(message(PSYCHOLOGIST, content), person)

    async def pay(self, txid: str, *, at: datetime) -> dict[str, int]:
        self.clock = at
        event = PixEvent(txid=txid, endToEndId="E2E" + txid[:10], valor="60.00", horario=at)
        return await self.webhook.receive(TOKEN, PixWebhookBody(pix=[event]))

    async def drain(self, limit: int = 10) -> int:
        processed = 0
        while processed < limit and await self.relay.process_next():
            processed += 1
        return processed

    def sent(self) -> list[tuple[str, str]]:
        return [(call.args[0].user_id, call.args[0].content) for call in self.outbound.publish.await_args_list]

    def patient_request(self) -> ImmediateRequestModel:
        recent = self.requests.list_recent(limit=1)
        assert recent, "no immediate request was created"
        assert recent[0].patient.phone_number == PATIENT
        return recent[0]


def message(phone: str, content: str) -> Message:
    return Message(
        event_id=f"e2e:{uuid4()}",
        message_id=int(hashlib.sha256(uuid4().bytes).hexdigest()[:12], 16),
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id=phone,
        chat_id=phone,
        content=content,
    )


async def reach_pix(world: World) -> str:
    """Drive the patient from "oi" to the Pix message; returns the txid."""
    start = await world.say(PATIENT, "oi")
    assert start.buttons is not None and "Quero ser paciente" in start.buttons
    await world.say(PATIENT, "Quero ser paciente")
    menu = await world.say(PATIENT, "Maria Silva")
    assert menu.buttons == ["Atendimento imediato", "Agendar atendimento"]
    triage = await world.say(PATIENT, "Atendimento imediato")
    assert triage.content.startswith("Antes de continuar, algumas perguntas rápidas.") and triage.buttons == ["Não", "Sim"]
    assert (await world.say(PATIENT, "Não")).buttons == ["Não", "Sim"]
    age = await world.say(PATIENT, "Não")
    assert age.content == "Você tem 18 anos ou mais?" and age.buttons == ["Sim", "Não"]
    terms = await world.say(PATIENT, "Sim")
    assert terms.buttons == ["Aceito os termos", "Não aceito"]
    duration = await world.say(PATIENT, "Aceito os termos")
    assert duration.content == "Valores: 30 minutos por R$ 60,00 ou 50 minutos por R$ 90,00.\n\nQuanto tempo você precisa?"
    assert duration.buttons == ["30 minutos", "50 minutos"]
    pix = await world.say(PATIENT, "30 minutos")
    assert pix.content.startswith("Valor: R$ 60,00\n\nPix copia e cola:\nPIX-SIMULADO-")
    assert pix.content.endswith("Se quiser desistir antes de pagar, mande CANCELAR.")
    request = world.patient_request()
    assert request.status == ImmediateStatus.AWAITING_PAYMENT.value
    assert request.pix_txid is not None
    return request.pix_txid


@pytest.fixture(autouse=True)
def immediate_care_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", True)  # simulated Pix and room


@pytest.mark.asyncio
async def test_patient_pays_professional_accepts_room_is_sent(db, redis_client) -> None:
    await redis_client.flushdb()
    world = World(db, redis_client)
    world.seed_psychologist(available=True)
    txid = await reach_pix(world)

    status = await world.say(PATIENT, "já paguei?")
    assert status.content.startswith("Ainda não recebi o pagamento. Pix copia e cola:\nPIX-SIMULADO-")

    assert await world.pay(txid, at=datetime.now(UTC)) == {"received": 1, "queued": 1}
    assert await world.pay(txid, at=datetime.now(UTC)) == {"received": 1, "queued": 0}
    assert await world.drain() == 1
    world.whatsapp.send_template.assert_awaited_once()
    offer = world.whatsapp.send_template.await_args.kwargs
    assert offer["to"] == PSYCHOLOGIST and offer["name"] == "acolhimento_oferta" and offer["body_parameters"] == ("Maria", "30", "60,00")
    assert world.sent() == [(PATIENT, "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos.")]
    context = await world.chats.get_context(PATIENT, Channel.WHATSAPP)
    assert context is not None and context.state == "imediato_na_fila"
    waiting = await world.say(PATIENT, "e aí?")
    assert waiting.content == (
        "Pagamento recebido!\n\nEstou procurando um psicólogo disponível. Te aviso aqui assim que alguém aceitar, em até 5 minutos."
    )

    reply = await world.professional_says("Aceitar")
    assert reply == Response(content=ACCEPTED_REPLY)
    assert await world.professional_says("Aceitar") == Response(content=ALREADY_YOURS_REPLY)
    request = world.patient_request()
    assert request.status == ImmediateStatus.ACCEPTED.value
    assert request.professional is not None and request.professional.phone_number == PSYCHOLOGIST

    assert await world.drain() == 1
    request = world.patient_request()
    assert request.room_url is not None and request.room_url.startswith("https://exemplo.daily.co/acolhimento-")
    assert request.patient_room_url == f"{request.room_url}?t=paciente"
    assert request.professional_room_url == f"{request.room_url}?t=profissional"
    assert world.sent()[1:] == [
        (
            PATIENT,
            f"Um psicólogo aceitou o seu atendimento! Entre na sala de vídeo: {request.patient_room_url}\n\n"
            "A sessão dura 30 minutos e não é gravada.",
        ),
        (PSYCHOLOGIST, f"Sala de vídeo do acolhimento: {request.professional_room_url}\n\nO paciente é Maria, sessão de 30 minutos."),
    ]
    context = await world.chats.get_context(PATIENT, Channel.WHATSAPP)
    assert context is not None and context.state == "imediato_na_fila"  # the patient can ask for the link again
    # the psychologist lost the link: tapping Aceitar again sends their own room link, never a second acceptance
    assert await world.professional_says("Aceitar") == Response(
        content=f"Você já ficou com esse atendimento. Sala de vídeo: {request.professional_room_url}"
    )
    assert await world.drain() == 0  # the 5-minute timeout is not due and will be a no-op when it is

    again = await world.say(PATIENT, "perdi o link")
    assert again.content.startswith(f"Seu atendimento já foi aceito. Sala de vídeo: {request.patient_room_url}")
    restart = await world.say(PATIENT, "oi")
    assert restart.buttons is not None and "Quero ser paciente" in restart.buttons


@pytest.mark.asyncio
async def test_nobody_accepts_refund_runs(db, redis_client) -> None:
    await redis_client.flushdb()
    world = World(db, redis_client)
    world.seed_psychologist(available=True)  # available, but never taps Aceitar
    txid = await reach_pix(world)

    assert await world.pay(txid, at=datetime.now(UTC) - timedelta(minutes=10)) == {"received": 1, "queued": 1}
    assert await world.drain() == 3  # timeout (overdue), offer (skipped: expired), refund
    world.whatsapp.send_template.assert_not_awaited()
    request = world.patient_request()
    assert request.status == ImmediateStatus.EXPIRED.value
    assert request.refunded_at is not None and request.pix_refund_id == f"{txid}R1"
    contents = [content for _phone, content in world.sent()]
    timeout_notice = "Nos últimos 5 minutos nenhum psicólogo ficou disponível. Vou devolver o seu Pix de R$ 60,00"
    assert any(content.startswith(timeout_notice) for content in contents)
    assert "Pix de R$ 60,00 devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET." in contents
    assert await world.chats.get_context(PATIENT, Channel.WHATSAPP) is None

    closed = await world.say(PATIENT, "oi")
    assert closed.buttons is not None and "Quero ser paciente" in closed.buttons
