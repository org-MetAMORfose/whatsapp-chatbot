from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.send_message_controller import SendMessageController, SendMessageRequest
from app.domain.enum.channels import Channel


@pytest.mark.asyncio
async def test_send_message_dispatches_correct_message() -> None:
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch = AsyncMock()

    controller = SendMessageController(dispatcher=mock_dispatcher)
    body = SendMessageRequest(phone_number="5511999999999", content="Hello!")

    result = await controller.send_message(body)

    assert result == {"status": "ok"}
    mock_dispatcher.dispatch.assert_awaited_once()

    dispatched = mock_dispatcher.dispatch.call_args.args[0]
    assert dispatched.channel == Channel.WHATSAPP
    assert dispatched.user_id == "5511999999999"
    assert dispatched.chat_id == "5511999999999"
    assert dispatched.content == "Hello!"
    assert isinstance(dispatched.message_id, int)
    assert dispatched.created_at is not None


def test_send_message_endpoint_returns_200_on_valid_body() -> None:
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch = AsyncMock()

    app = FastAPI()
    controller = SendMessageController(dispatcher=mock_dispatcher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"phone_number": "5511999999999", "content": "Test"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_send_message_endpoint_returns_200_when_only_phone_number_is_provided() -> None:
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch = AsyncMock()

    app = FastAPI()
    controller = SendMessageController(dispatcher=mock_dispatcher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"phone_number": "5511999999999"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_send_message_endpoint_returns_422_when_content_is_missing() -> None:
    mock_dispatcher = MagicMock()
    # Define o método dispatch como assíncrono
    mock_dispatcher.dispatch = AsyncMock() 

    app = FastAPI()
    controller = SendMessageController(dispatcher=mock_dispatcher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"phone_number": "5511999999999"})

    assert response.status_code == 422

def test_generate_message_id_returns_unique_ints() -> None:
    controller = SendMessageController(dispatcher=MagicMock())
    id1 = controller._generate_message_id()
    id2 = controller._generate_message_id()
    assert isinstance(id1, int)
    assert isinstance(id2, int)
    assert id1 != id2
