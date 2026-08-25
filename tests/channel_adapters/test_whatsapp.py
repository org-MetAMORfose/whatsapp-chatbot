from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.s3_media_service import S3MediaService, StoredMedia


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
    mock_response.json.return_value = {"id": "whatsapp-media-id"}
    mock_client.post.return_value = mock_response

    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)

    mock_async_client_cls.return_value = mock_async_client

    # Executa
    await adapter.send_message(message)

    version = adapter.version
    expected_url = f"https://graph.facebook.com/{version}/123456/messages"

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
    mock_response.json.return_value = {"id": "whatsapp-media-id"}
    mock_client.post.return_value = mock_response
    mock_async_client = MagicMock()
    mock_async_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client, mock_response, mock_async_client


def _make_s3_service(media_path: str, content_type: str) -> MagicMock:
    service = MagicMock(spec=S3MediaService)
    service.get_file = AsyncMock(
        return_value=StoredMedia(
            path=media_path,
            content=b"media-bytes",
            content_type=content_type,
            filename=media_path.rsplit("/", 1)[-1],
        )
    )
    return service


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_image_message(mock_async_client_cls: MagicMock) -> None:
    media_path = "media/image/abc.jpg"
    s3_service = _make_s3_service(media_path, "image/jpeg")
    adapter = WhatsAppAdapter(
        access_token="fake-token",
        phone_number_id="123456",
        s3_service=s3_service,
    )
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=2,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content=None,
        media=media_path,
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "image"
    assert payload["image"]["id"] == "whatsapp-media-id"
    assert "text" not in payload
    s3_service.get_file.assert_awaited_once_with(media_path)


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_document_message(mock_async_client_cls: MagicMock) -> None:
    media_path = "media/document/abc.pdf"
    s3_service = _make_s3_service(media_path, "application/pdf")
    adapter = WhatsAppAdapter(
        access_token="fake-token",
        phone_number_id="123456",
        s3_service=s3_service,
    )
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=3,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content=None,
        media=media_path,
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "document"
    assert payload["document"]["id"] == "whatsapp-media-id"
    assert payload["document"]["filename"] == "abc.pdf"
    assert "text" not in payload
    s3_service.get_file.assert_awaited_once_with(media_path)


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_video_message(mock_async_client_cls: MagicMock) -> None:
    media_path = "media/video/qualification.mp4"
    s3_service = _make_s3_service(media_path, "video/mp4")
    adapter = WhatsAppAdapter(
        access_token="fake-token",
        phone_number_id="123456",
        s3_service=s3_service,
    )
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=4,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content="Vídeo de qualificação",
        media=media_path,
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "video"
    assert payload["video"]["id"] == "whatsapp-media-id"
    assert payload["video"]["caption"] == "Vídeo de qualificação"
    s3_service.get_file.assert_awaited_once_with(media_path)


@pytest.mark.asyncio
@patch("app.channel_adapters.whatsapp.httpx.AsyncClient")
async def test_send_image_with_caption(mock_async_client_cls: MagicMock) -> None:
    media_path = "media/image/abc.jpg"
    adapter = WhatsAppAdapter(
        access_token="fake-token",
        phone_number_id="123456",
        s3_service=_make_s3_service(media_path, "image/jpeg"),
    )
    mock_client, _, mock_async_client = _make_mock_client()
    mock_async_client_cls.return_value = mock_async_client

    message = Message(
        message_id=4,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="user",
        chat_id="5511999999999",
        content="Confira o anexo",
        media=media_path,
    )

    await adapter.send_message(message)

    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["type"] == "image"
    assert payload["image"]["caption"] == "Confira o anexo"
