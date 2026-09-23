from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.context import AppContext
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.dispatcher_service import MessageDispatcherService


def message() -> Message:
    return Message(message_id=1, event_id="reply:abc", channel=Channel.WHATSAPP,
                   chat_id="123", user_id="123", content="hello", created_at=datetime.now(UTC))


@pytest.mark.asyncio
async def test_missing_adapter_fails_for_retry() -> None:
    dispatcher = MessageDispatcherService(AppContext(), MagicMock(), MagicMock())
    with pytest.raises(ValueError, match="No adapter"):
        await dispatcher.dispatch(message())


@pytest.mark.asyncio
async def test_completed_delivery_does_not_send_again() -> None:
    people = MagicMock()
    people._session_factory.return_value.__enter__.return_value.get.return_value = object()
    dispatcher = MessageDispatcherService(AppContext(), MagicMock(), people)
    adapter = MagicMock(send_message=AsyncMock())
    dispatcher.register_adapter(Channel.WHATSAPP, adapter)
    await dispatcher.dispatch(message())
    adapter.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_failure_is_not_recorded_as_success() -> None:
    people = MagicMock()
    people._session_factory.return_value.__enter__.return_value.get.return_value = None
    dispatcher = MessageDispatcherService(AppContext(), MagicMock(), people)
    adapter = MagicMock(send_message=AsyncMock(side_effect=TimeoutError()))
    dispatcher.register_adapter(Channel.WHATSAPP, adapter)
    with pytest.raises(TimeoutError):
        await dispatcher.dispatch(message())
    people.create_message.assert_not_called()
