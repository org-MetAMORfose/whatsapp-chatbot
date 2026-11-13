from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.agent import Response
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.services.immediate_care_interceptor import ImmediateCareInterceptor

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
PERSON = PersonModel(id=9, phone_number="5511977776666", channel=Channel.WHATSAPP, name="Dra. Ana")


def professional(area: str = "Psicoterapia") -> ProfessionalModel:
    return ProfessionalModel(id=3, person_id=9, area=area, professional_register="1", register_type="CRP")


def message(content: str) -> Message:
    return Message(message_id=1, channel=Channel.WHATSAPP, created_at=NOW, user_id="5511977776666", chat_id="5511977776666", content=content)


def make_interceptor(*, found: ProfessionalModel | None, offer: int | None = None, accepted: bool = True):
    professionals = MagicMock(spec=ProfessionalRepository)
    professionals.get_by_person_id.return_value = found
    professionals.set_available_for_immediate.return_value = found
    requests = MagicMock(spec=ImmediateRequestRepository)
    requests.accept.return_value = accepted
    offers = MagicMock()
    offers.get = AsyncMock(return_value=offer)
    offers.clear = AsyncMock()
    outbox = MagicMock()
    interceptor = ImmediateCareInterceptor(professionals, requests, offers, outbox, now=lambda: NOW)
    return interceptor, professionals, requests, offers, outbox


@pytest.mark.asyncio
async def test_non_professional_is_ignored() -> None:
    interceptor, professionals, _requests, _offers, _outbox = make_interceptor(found=None)
    assert await interceptor.handle(message("Disponível"), PERSON) is None
    assert await interceptor.handle(message("Aceitar"), PERSON) is None
    professionals.set_available_for_immediate.assert_not_called()


@pytest.mark.asyncio
async def test_unrelated_text_returns_none() -> None:
    interceptor, _professionals, _requests, _offers, _outbox = make_interceptor(found=professional())
    assert await interceptor.handle(message("oi, tudo bem?"), PERSON) is None
    assert await interceptor.handle(message(""), PERSON) is None


@pytest.mark.asyncio
async def test_available_sets_flag_and_replies() -> None:
    interceptor, professionals, _requests, _offers, _outbox = make_interceptor(found=professional())
    response = await interceptor.handle(message("DISPONÍVEL"), PERSON)
    assert response == Response(content="Pronto! Você está disponível para acolhimento imediato. Quando quiser sair, mande INDISPONÍVEL.")
    professionals.set_available_for_immediate.assert_called_once_with(9, True, now=NOW)


@pytest.mark.asyncio
async def test_available_refused_for_non_psychotherapy() -> None:
    interceptor, professionals, _requests, _offers, _outbox = make_interceptor(found=professional("Nutrição"))
    response = await interceptor.handle(message("disponivel"), PERSON)
    assert response == Response(content="Por enquanto o acolhimento imediato é só para psicólogos.")
    professionals.set_available_for_immediate.assert_not_called()


@pytest.mark.asyncio
async def test_unavailable_clears_flag() -> None:
    interceptor, professionals, _requests, _offers, _outbox = make_interceptor(found=professional())
    response = await interceptor.handle(message("Indisponível"), PERSON)
    assert response == Response(
        content="Combinado, você não vai mais receber ofertas de acolhimento imediato. Mande DISPONÍVEL quando quiser voltar."
    )
    professionals.set_available_for_immediate.assert_called_once_with(9, False, now=NOW)


@pytest.mark.asyncio
async def test_accept_without_offer() -> None:
    interceptor, _professionals, requests, _offers, outbox = make_interceptor(found=professional(), offer=None)
    response = await interceptor.handle(message("Aceitar"), PERSON)
    assert response == Response(content="Não há nenhuma oferta de acolhimento aberta para você agora.")
    requests.accept.assert_not_called()
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_accept_wins_enqueues_accepted_and_clears_offer() -> None:
    interceptor, _professionals, requests, offers, outbox = make_interceptor(found=professional(), offer=42, accepted=True)
    response = await interceptor.handle(message("Aceitar"), PERSON)
    assert response == Response(content="Você ficou com o atendimento! Estou criando a sala de vídeo e te mando o link em instantes.")
    requests.accept.assert_called_once_with(42, professional_person_id=9, now=NOW)
    outbox.enqueue.assert_called_once_with("immediate:42:accepted", "immediate.accepted.v1", {"request_id": 42})
    offers.clear.assert_awaited_once_with("5511977776666", Channel.WHATSAPP)


@pytest.mark.asyncio
async def test_accept_loser_gets_already_taken() -> None:
    interceptor, _professionals, requests, offers, outbox = make_interceptor(found=professional(), offer=42, accepted=False)
    response = await interceptor.handle(message("aceitar"), PERSON)
    assert response == Response(content="Esse atendimento já foi aceito por outro profissional ou o prazo acabou.")
    requests.accept.assert_called_once_with(42, professional_person_id=9, now=NOW)
    outbox.enqueue.assert_not_called()
    offers.clear.assert_awaited_once_with("5511977776666", Channel.WHATSAPP)


@pytest.mark.asyncio
async def test_processor_answers_with_interceptor_before_the_flow() -> None:
    from app.domain.enum.chat_mode import ChatMode
    from app.infra.message_queue import Delivery
    from app.services.inbound_processor import InboundProcessor

    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    session.get.return_value = None
    people = MagicMock()
    people.get_or_create_person.return_value = PersonModel(
        id=9, phone_number="5511977776666", channel=Channel.WHATSAPP, chat_mode=ChatMode.AUTOMATIC
    )
    people.create_message.return_value = MagicMock(id=10)
    agent = MagicMock()
    agent._process_message = AsyncMock(return_value=Response(content="fluxo normal"))
    follow_ups = MagicMock()
    follow_ups.consume = AsyncMock(return_value=False)
    interceptor = MagicMock()
    interceptor.handle = AsyncMock(side_effect=[Response(content="ok, disponível"), None])
    inbound = MagicMock()
    inbound.complete_inbound = AsyncMock()
    processor = InboundProcessor(factory, agent, people, inbound, MagicMock(), None, follow_ups, interceptor=interceptor)

    first = Message(
        event_id="first",
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="5511977776666",
        chat_id="5511977776666",
        content="Disponível",
    )
    second = first.model_copy(update={"event_id": "second", "message_id": 2, "content": "oi"})
    await processor.process(Delivery("delivery-1", first.model_dump_json(), 1))
    await processor.process(Delivery("delivery-2", second.model_dump_json(), 1))

    first_result = inbound.complete_inbound.await_args_list[0].args[1]
    second_result = inbound.complete_inbound.await_args_list[1].args[1]
    assert first_result["response"]["content"] == "ok, disponível"
    assert second_result["response"]["content"] == "fluxo normal"
    agent._process_message.assert_awaited_once()
    assert interceptor.handle.await_args_list[0].args[1].id == 9
