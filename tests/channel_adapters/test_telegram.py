from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channel_adapters.telegram import TelegramAdapter
from app.domain.channels import Channel


@pytest.mark.asyncio
async def test_callback_wrapper_converts_valid_update_to_message() -> None:
    adapter = TelegramAdapter(token="fake-token", ctx=MagicMock())
    callback = AsyncMock()

    wrapped_callback = adapter._TelegramAdapter__callback_wrapper(callback)

    created_at = datetime.now(UTC)
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=123),
        effective_user=SimpleNamespace(id=456),
        message=SimpleNamespace(
            text="hello world",
            message_id=789,
            date=created_at,
        ),
    )
    context = MagicMock()

    await wrapped_callback(update, context)

    await_args = callback.await_args
    assert await_args is not None
    message = await_args.args[0]

    assert message.message_id == 789
    assert message.channel == Channel.TELEGRAM
    assert message.created_at == created_at
    assert message.chat_id == "123"
    assert message.user_id == "456"
    assert message.content == "hello world"


@pytest.mark.asyncio
@patch("app.channel_adapters.telegram.MessageHandler")
@patch("app.channel_adapters.telegram.Application")
async def test_start_listener_builds_app_registers_handler_and_starts_polling(
    mock_application,
    mock_message_handler,
) -> None:
    adapter = TelegramAdapter(token="fake-token", ctx=MagicMock())
    callback = AsyncMock()

    mock_app = MagicMock()
    mock_app.add_handler = MagicMock()
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.updater = MagicMock()
    mock_app.updater.start_polling = AsyncMock()

    mock_builder = MagicMock()
    mock_builder.bot.return_value = mock_builder
    mock_builder.build.return_value = mock_app
    mock_application.builder.return_value = mock_builder

    await adapter.start_listener(callback)

    mock_application.builder.assert_called_once()
    mock_builder.bot.assert_called_once_with(adapter.bot)
    mock_builder.build.assert_called_once()
    mock_message_handler.assert_called_once()
    mock_app.add_handler.assert_called_once_with(mock_message_handler.return_value)
    mock_app.initialize.assert_awaited_once()
    mock_app.start.assert_awaited_once()
    mock_app.updater.start_polling.assert_awaited_once()
    assert adapter.app is mock_app


@pytest.mark.asyncio
async def test_stop_listener_stops_app_when_present() -> None:
    adapter = TelegramAdapter(token="fake-token", ctx=MagicMock())

    mock_app = MagicMock()
    mock_app.stop = AsyncMock()
    adapter.app = mock_app

    await adapter.stop_listener()

    mock_app.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_listener_does_nothing_when_app_is_none() -> None:
    adapter = TelegramAdapter(token="fake-token", ctx=MagicMock())
    adapter.app = None

    await adapter.stop_listener()