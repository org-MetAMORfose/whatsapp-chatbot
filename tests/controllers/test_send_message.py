from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.send_message_controller import SendMessageController, SendMessageRequest
from app.domain.enum.channels import Channel


@pytest.mark.asyncio
async def test_send_message_publishes_correct_message() -> None:
    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock()

    controller = SendMessageController(outbound_queue=mock_publisher)
    body = SendMessageRequest(phone_number="5511999999999", content="Hello!")

    result = await controller.send_message(body)

    assert result == {"status": "accepted"}
    mock_publisher.publish.assert_awaited_once()

    published = mock_publisher.publish.call_args.args[0]
    assert published.channel == Channel.WHATSAPP
    assert published.user_id == "5511999999999"
    assert published.chat_id == "5511999999999"
    assert published.content == "Hello!"
    assert isinstance(published.message_id, int)
    assert published.created_at is not None


def test_send_message_endpoint_returns_202_on_valid_body() -> None:
    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock()

    app = FastAPI()
    controller = SendMessageController(outbound_queue=mock_publisher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"phone_number": "5511999999999", "content": "Test"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}


def test_send_message_endpoint_returns_202_when_only_phone_number_is_provided() -> None:
    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock()

    app = FastAPI()
    controller = SendMessageController(outbound_queue=mock_publisher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"phone_number": "5511999999999"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}


def test_send_message_endpoint_accepts_media_path() -> None:
    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock()
    app = FastAPI()
    controller = SendMessageController(outbound_queue=mock_publisher)
    app.include_router(controller.router)

    response = TestClient(app).post(
        "/send",
        json={
            "phone_number": "5511999999999",
            "media": "media/document/registration.pdf",
        },
    )

    assert response.status_code == 202
    published = mock_publisher.publish.call_args.args[0]
    assert published.media == "media/document/registration.pdf"


def test_send_message_endpoint_rejects_media_url() -> None:
    mock_publisher = MagicMock()
    mock_publisher.publish = AsyncMock()
    app = FastAPI()
    controller = SendMessageController(outbound_queue=mock_publisher)
    app.include_router(controller.router)

    response = TestClient(app).post(
        "/send",
        json={
            "phone_number": "5511999999999",
            "media": "https://bucket.s3.amazonaws.com/media/image/file.jpg",
        },
    )

    assert response.status_code == 422
    mock_publisher.publish.assert_not_awaited()


def test_send_message_endpoint_returns_422_when_phone_number_is_missing() -> None:
    mock_publisher = MagicMock()

    app = FastAPI()
    controller = SendMessageController(outbound_queue=mock_publisher)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post("/send", json={"content": "Hello"})

    assert response.status_code == 422


def test_generate_message_id_returns_unique_ints() -> None:
    controller = SendMessageController(outbound_queue=MagicMock())
    id1 = controller._generate_message_id()
    id2 = controller._generate_message_id()
    assert isinstance(id1, int)
    assert isinstance(id2, int)
    assert id1 != id2
