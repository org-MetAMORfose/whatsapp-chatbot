from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.enum.channels import Channel
from app.domain.message import Message


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_message_sends_correct_request(
    mock_async_client_cls: MagicMock,
) -> None:
    adapter = WhatsAppAdapter(
        access_token="fake-token",
        phone_number_id="123456",
        ctx=MagicMock(),
    )

    message = Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content="hello world",
    )

    # Mock do client dentro do async with
    mock_client = MagicMock()
    mock_client.post = AsyncMock()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)

    mock_async_client_cls.return_value = mock_async_client

    # Executa
    await adapter.send_message(message)

    expected_url = "https://graph.facebook.com/v23.0/123456/messages"

    expected_headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
    }

    expected_payload = {
        "messaging_product": "whatsapp",
        "to": "5511999999999",
        "type": "text",
        "text": {
            "body": "hello world",
        },
    }

    # Verifica chamada HTTP
    mock_client.post.assert_awaited_once_with(
        expected_url,
        headers=expected_headers,
        json=expected_payload,
    )

    # Verifica que validou status
    mock_response.raise_for_status.assert_called_once()


def _make_mock_client() -> tuple[MagicMock, MagicMock, MagicMock]:
    mock_client = MagicMock()
    mock_client.post = AsyncMock()
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response
    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client, mock_response, mock_async_client


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_image_message(mock_async_client_cls: MagicMock) -> None:
    adapter = WhatsAppAdapter(access_token="fake-token", phone_number_id="123456")
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=2,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content=None,
        image="https://bucket.s3.amazonaws.com/media/image/abc.jpg",
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "image"
    assert payload["image"]["link"] == "https://bucket.s3.amazonaws.com/media/image/abc.jpg"
    assert "text" not in payload


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_document_message(mock_async_client_cls: MagicMock) -> None:
    adapter = WhatsAppAdapter(access_token="fake-token", phone_number_id="123456")
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=3,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content=None,
        document="https://bucket.s3.amazonaws.com/media/document/abc.pdf",
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "document"
    assert payload["document"]["link"] == "https://bucket.s3.amazonaws.com/media/document/abc.pdf"
    assert "text" not in payload


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_image_with_caption(mock_async_client_cls: MagicMock) -> None:
    adapter = WhatsAppAdapter(access_token="fake-token", phone_number_id="123456")
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=4,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content="Confira o anexo",
        image="https://bucket.s3.amazonaws.com/media/image/abc.jpg",
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "image"
    assert payload["image"]["caption"] == "Confira o anexo"
