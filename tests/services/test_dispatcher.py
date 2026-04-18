import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.context import AppContext
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.interfaces.bot_adapter import BotAdapter
from app.message_queue.message_queue import MessageQueue
from app.services.dispatcher_service import MessageDispatcherService


@pytest.fixture
def mock_context() -> MagicMock:
    ctx = MagicMock(spec=AppContext)
    return ctx


@pytest.fixture
def mock_outbound_queue() -> MagicMock:
    return MagicMock(spec=MessageQueue)


@pytest.fixture
def dispatcher(
    mock_context: MagicMock,
    mock_outbound_queue: MagicMock,
) -> MessageDispatcherService:
    return MessageDispatcherService(
        ctx=mock_context,
        outbound_queue=mock_outbound_queue,
    )


@pytest.fixture
def telegram_adapter() -> MagicMock:
    adapter = MagicMock(spec=BotAdapter)
    adapter.send_message = AsyncMock()
    return adapter


@pytest.fixture
def whatsapp_adapter() -> MagicMock:
    adapter = MagicMock(spec=BotAdapter)
    adapter.send_message = AsyncMock()
    return adapter


def make_message(channel: Channel, chat_id: str, user_id: str, content: str) -> Message:
    return Message(
        message_id=1 if channel == Channel.TELEGRAM else 2,
        created_at=datetime.now(UTC),
        channel=channel,
        chat_id=chat_id,
        user_id=user_id,
        content=content,
    )


@pytest.mark.asyncio
async def test_dispatch_sends_message_to_registered_channel_adapter(
    dispatcher: MessageDispatcherService,
    telegram_adapter: MagicMock,
) -> None:
    dispatcher.register_adapter(Channel.TELEGRAM, telegram_adapter)

    message = make_message(
        channel=Channel.TELEGRAM,
        chat_id="123",
        user_id="user_1",
        content="Hello",
    )

    await dispatcher.dispatch(message)

    telegram_adapter.send_message.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_dispatch_uses_correct_adapter_when_two_channels_are_registered(
    dispatcher: MessageDispatcherService,
    telegram_adapter: MagicMock,
    whatsapp_adapter: MagicMock,
) -> None:
    dispatcher.register_adapter(Channel.TELEGRAM, telegram_adapter)
    dispatcher.register_adapter(Channel.WHATSAPP, whatsapp_adapter)

    telegram_message = make_message(
        channel=Channel.TELEGRAM,
        chat_id="123",
        user_id="user_1",
        content="hello telegram",
    )
    whatsapp_message = make_message(
        channel=Channel.WHATSAPP,
        chat_id="5511999999999",
        user_id="user_2",
        content="hello whatsapp",
    )

    await dispatcher.dispatch(telegram_message)
    await dispatcher.dispatch(whatsapp_message)

    telegram_adapter.send_message.assert_awaited_once_with(telegram_message)
    whatsapp_adapter.send_message.assert_awaited_once_with(whatsapp_message)


@pytest.mark.asyncio
async def test_start_creates_and_stores_task(
    dispatcher: MessageDispatcherService,
) -> None:
    mock_task = MagicMock()

    with patch(
        "app.services.dispatcher_service.asyncio.create_task", return_value=mock_task
    ) as mock_create_task:
        await dispatcher.start()

    mock_create_task.assert_called_once()
    assert dispatcher._task is mock_task


@pytest.mark.asyncio
async def test_stop_cancels_and_awaits_existing_task(
    dispatcher: MessageDispatcherService,
) -> None:
    task = asyncio.Future()
    task.set_result(None)
    task.cancel = MagicMock()  # type: ignore[method-assign]

    dispatcher._task = task  # type: ignore[assignment]

    await dispatcher.stop()

    task.cancel.assert_called_once()
