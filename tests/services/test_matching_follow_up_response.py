from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.agent import Response
from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message
from app.infra.message_queue import Delivery
from app.repository.redis.matching_follow_up_repository import MatchingFollowUpRepository
from app.services.inbound_processor import FOLLOW_UP_THANK_YOU, InboundProcessor


@pytest.mark.asyncio
async def test_follow_up_marker_lasts_three_days_and_is_consumed_once() -> None:
    repository = MatchingFollowUpRepository(MagicMock())
    state = MagicMock()
    state.set = AsyncMock()
    state.get = AsyncMock(side_effect=["pending", None])
    state.delete = AsyncMock(return_value=1)
    repository.redis_client = state

    await repository.mark("5511999991111", Channel.WHATSAPP)

    state.set.assert_awaited_once_with(
        "matching_follow_up:WHATSAPP:5511999991111",
        "pending",
        ex=3 * 24 * 60 * 60,
    )
    assert await repository.consume("5511999991111", Channel.WHATSAPP)
    assert not await repository.consume("5511999991111", Channel.WHATSAPP)
    state.delete.assert_awaited_once_with("matching_follow_up:WHATSAPP:5511999991111")


@pytest.mark.asyncio
@pytest.mark.parametrize("button", ["Já conversamos", "Tentei, sem resposta", "Não quero continuar"])
async def test_marked_reply_only_thanks_then_next_message_returns_to_normal_flow(
    button: str,
) -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    session.get.return_value = None

    people = MagicMock()
    people.get_or_create_person.side_effect = [
        PersonModel(
            id=1,
            phone_number="5511999991111",
            channel=Channel.WHATSAPP,
            chat_mode=ChatMode.MANUAL,
        ),
        PersonModel(
            id=1,
            phone_number="5511999991111",
            channel=Channel.WHATSAPP,
            chat_mode=ChatMode.AUTOMATIC,
        ),
    ]
    people.create_message.return_value = MagicMock(id=10)

    agent = MagicMock()
    agent._process_message = AsyncMock(return_value=Response(content="fluxo normal"))
    follow_ups = MagicMock()
    follow_ups.consume = AsyncMock(side_effect=[True, False])
    inbound = MagicMock()
    inbound.complete_inbound = AsyncMock()
    outbound = MagicMock()
    processor = InboundProcessor(
        factory,
        agent,
        people,
        inbound,
        outbound,
        None,
        follow_ups,
    )

    first_message = Message(
        event_id="first",
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="5511999991111",
        chat_id="5511999991111",
        content=button,
    )
    second_message = first_message.model_copy(update={"event_id": "second", "message_id": 2, "content": "Olá"})

    await processor.process(Delivery("delivery-1", first_message.model_dump_json(), 1))
    await processor.process(Delivery("delivery-2", second_message.model_dump_json(), 1))

    first_result = inbound.complete_inbound.await_args_list[0].args[1]
    second_result = inbound.complete_inbound.await_args_list[1].args[1]
    assert first_result["response"]["content"] == FOLLOW_UP_THANK_YOU
    assert first_result["response"]["buttons"] is None
    assert second_result["response"]["content"] == "fluxo normal"
    agent._process_message.assert_awaited_once()
