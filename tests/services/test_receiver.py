from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enum.channels import Channel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message
from app.message_queue.message_queue import MessageQueue
from app.services.receiver_service import MessageReceiverService


@pytest.mark.asyncio
async def test_handle_queues_the_persisted_message_history_id() -> None:

    inbound_queue = MagicMock(spec=MessageQueue)
    inbound_queue.publish = AsyncMock()

    person_repository = MagicMock()
    person_repository.get_or_create_person.return_value = MagicMock(
        id=10,
        chat_mode=ChatMode.AUTOMATIC,
    )
    person_repository.create_message.return_value = MagicMock(id=99)
    service = MessageReceiverService(
        inbound_queue=inbound_queue,
        person_repository=person_repository,
    )

    message = Message(
        message_id=1,
        created_at=datetime.now(UTC),
        channel=Channel.TELEGRAM,
        chat_id="123",
        user_id="user_1",
        content="Hello",
    )

    await service.handle(message)

    inbound_queue.publish.assert_awaited_once()
    queued_message = inbound_queue.publish.await_args.args[0]
    assert queued_message.history_id == 99
    assert message.history_id is None
    persisted_message = person_repository.create_message.call_args.args[0]
    assert persisted_message.person_id == 10
    assert persisted_message.content == "Hello"
    assert persisted_message.is_from_user is True


@pytest.mark.asyncio
async def test_handle_saves_history_but_does_not_queue_when_agent_stopped() -> None:
    inbound_queue = MagicMock(spec=MessageQueue)
    inbound_queue.publish = AsyncMock()
    person_repository = MagicMock()
    person_repository.get_or_create_person.return_value = MagicMock(
        id=11,
        chat_mode=ChatMode.MANUAL,
    )
    service = MessageReceiverService(
        inbound_queue=inbound_queue,
        person_repository=person_repository,
    )
    message = Message(
        message_id=2,
        created_at=datetime.now(UTC),
        channel=Channel.WHATSAPP,
        chat_id="456",
        user_id="user_2",
        content="Preciso falar com alguém",
    )

    await service.handle(message)

    person_repository.create_message.assert_called_once()
    inbound_queue.publish.assert_not_awaited()
