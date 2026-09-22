from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.receiver_service import MessageReceiverService


@pytest.mark.asyncio
async def test_ingress_only_publishes_and_propagates_redis_failure() -> None:
    queue = AsyncMock()
    receiver = MessageReceiverService(queue)
    message = Message(message_id=1, created_at=datetime.now(UTC), channel=Channel.WHATSAPP,
                      chat_id="123", user_id="123", content="hello")
    await receiver.handle(message)
    queue.publish.assert_awaited_once_with(message)
    queue.publish.side_effect = ConnectionError("Redis unavailable")
    with pytest.raises(ConnectionError):
        await receiver.handle(message)
