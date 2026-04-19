from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runners.telegram_runner import TelegramRunner


@pytest.mark.asyncio
@patch("app.runners.telegram_runner.MessageDispatcherService")
@patch("app.runners.telegram_runner.TelegramAdapter")
async def test_start_calls_dispatcher_and_listener(
    mock_telegram_adapter_cls,
    mock_dispatcher_cls,
) -> None:
    ctx = MagicMock()
    outbound_queue = MagicMock()
    message_receiver = MagicMock()
    message_receiver.handle = AsyncMock()
    token = "fake-token"

    mock_adapter = MagicMock()
    mock_adapter.channel = "telegram"
    mock_adapter.start_listener = AsyncMock()
    mock_telegram_adapter_cls.return_value = mock_adapter

    mock_dispatcher = MagicMock()
    mock_dispatcher.start = AsyncMock()
    mock_dispatcher_cls.return_value = mock_dispatcher

    runner = TelegramRunner(
        ctx=ctx,
        outbound_queue=outbound_queue,
        message_receiver=message_receiver,
        token=token,
        person_repository=MagicMock(),
    )

    await runner.start()

    mock_dispatcher.start.assert_awaited_once()
    mock_adapter.start_listener.assert_awaited_once_with(callback=message_receiver.handle)


@pytest.mark.asyncio
@patch("app.runners.telegram_runner.MessageDispatcherService")
@patch("app.runners.telegram_runner.TelegramAdapter")
async def test_stop_calls_listener_and_dispatcher_stop(
    mock_telegram_adapter_cls,
    mock_dispatcher_cls,
) -> None:
    ctx = MagicMock()
    outbound_queue = MagicMock()
    message_receiver = MagicMock()
    token = "fake-token"

    mock_adapter = MagicMock()
    mock_adapter.channel = "telegram"
    mock_adapter.stop_listener = AsyncMock()
    mock_telegram_adapter_cls.return_value = mock_adapter

    mock_dispatcher = MagicMock()
    mock_dispatcher.stop = AsyncMock()
    mock_dispatcher_cls.return_value = mock_dispatcher

    runner = TelegramRunner(
        ctx=ctx,
        outbound_queue=outbound_queue,
        message_receiver=message_receiver,
        token=token,
        person_repository=MagicMock(),
    )

    await runner.stop()

    mock_adapter.stop_listener.assert_awaited_once()
    mock_dispatcher.stop.assert_awaited_once()
