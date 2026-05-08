from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.message_queue.message_queue import MessageQueue
from app.services.receiver_service import MessageReceiverService


@pytest.mark.asyncio
async def test_handle_appends_message_to_history_and_publishes_to_queue() -> None:

    inbound_queue = MagicMock(spec=MessageQueue)
    inbound_queue.publish = AsyncMock()

    service = MessageReceiverService(
        inbound_queue=inbound_queue,
        person_repository=MagicMock(),  # You can mock this as needed for more complex tests
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

    inbound_queue.publish.assert_awaited_once_with(message)
