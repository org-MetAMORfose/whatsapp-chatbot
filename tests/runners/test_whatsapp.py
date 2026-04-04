import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.runners.whatsapp_runner import WhatsAppRunner


@pytest.mark.asyncio
@patch("app.runners.whatsapp_runner.asyncio.create_task")
@patch("app.runners.whatsapp_runner.uvicorn.Server")
@patch("app.runners.whatsapp_runner.uvicorn.Config")
@patch("app.runners.whatsapp_runner.FastAPI")
@patch("app.runners.whatsapp_runner.WhatsAppController")
@patch("app.runners.whatsapp_runner.MessageDispatcherService")
@patch("app.runners.whatsapp_runner.WhatsAppAdapter")
async def test_start_calls_dispatcher_and_creates_server_task(
    mock_whatsapp_adapter_cls: MagicMock,
    mock_dispatcher_cls: MagicMock,
    mock_controller_cls: MagicMock,
    mock_fastapi_cls: MagicMock,
    mock_uvicorn_config_cls: MagicMock,
    mock_uvicorn_server_cls: MagicMock,
    mock_create_task: MagicMock,
) -> None:
    ctx = MagicMock()
    outbound_queue = MagicMock()
    message_handler = MagicMock()

    mock_adapter = MagicMock()
    mock_adapter.channel = "whatsapp"
    mock_whatsapp_adapter_cls.return_value = mock_adapter

    mock_dispatcher = MagicMock()
    mock_dispatcher.start = AsyncMock()
    mock_dispatcher_cls.return_value = mock_dispatcher

    mock_controller = MagicMock()
    mock_controller.router = MagicMock()
    mock_controller_cls.return_value = mock_controller

    mock_app = MagicMock()
    mock_fastapi_cls.return_value = mock_app

    mock_config = MagicMock()
    mock_uvicorn_config_cls.return_value = mock_config

    mock_server = MagicMock()
    mock_server.serve = AsyncMock()
    mock_uvicorn_server_cls.return_value = mock_server

    mock_server_task = MagicMock()
    mock_create_task.return_value = mock_server_task

    runner = WhatsAppRunner(
        ctx=ctx,
        outbound_queue=outbound_queue,
        message_handler=message_handler,
    )

    await runner.start()

    mock_dispatcher.start.assert_awaited_once()
    mock_uvicorn_config_cls.assert_called_once()
    mock_uvicorn_server_cls.assert_called_once_with(mock_config)
    mock_create_task.assert_called_once()

    assert runner.server is mock_server
    assert runner.server_task is mock_server_task


@pytest.mark.asyncio
@patch("app.runners.whatsapp_runner.FastAPI")
@patch("app.runners.whatsapp_runner.WhatsAppController")
@patch("app.runners.whatsapp_runner.MessageDispatcherService")
@patch("app.runners.whatsapp_runner.WhatsAppAdapter")
async def test_stop_sets_server_exit_awaits_task_and_stops_dispatcher(
    mock_whatsapp_adapter_cls: MagicMock,
    mock_dispatcher_cls: MagicMock,
    mock_controller_cls: MagicMock,
    mock_fastapi_cls: MagicMock,
) -> None:
    ctx = MagicMock()
    outbound_queue = MagicMock()
    message_handler = MagicMock()

    mock_adapter = MagicMock()
    mock_adapter.channel = "whatsapp"
    mock_whatsapp_adapter_cls.return_value = mock_adapter

    mock_dispatcher = MagicMock()
    mock_dispatcher.stop = AsyncMock()
    mock_dispatcher_cls.return_value = mock_dispatcher

    mock_controller = MagicMock()
    mock_controller.router = MagicMock()
    mock_controller_cls.return_value = mock_controller

    mock_app = MagicMock()
    mock_fastapi_cls.return_value = mock_app

    runner = WhatsAppRunner(
        ctx=ctx,
        outbound_queue=outbound_queue,
        message_handler=message_handler,
    )

    mock_server = MagicMock()
    mock_server.should_exit = False
    runner.server = mock_server

    async def _dummy_server_task() -> None:
        return None

    server_task: asyncio.Task[None] = asyncio.create_task(_dummy_server_task())
    runner.server_task = server_task

    await runner.stop()

    assert mock_server.should_exit is True
    mock_dispatcher.stop.assert_awaited_once()