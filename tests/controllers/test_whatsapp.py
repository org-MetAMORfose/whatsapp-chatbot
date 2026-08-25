from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.controllers.whatsapp_controller import WhatsAppController, _ParsedWhatsAppMessage
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.s3_media_service import S3MediaService


@pytest.mark.asyncio
async def test_receive_webhook_forwards_extracted_messages_to_handler() -> None:
    message_handler = MagicMock()
    message_handler.handle = AsyncMock()

    controller = WhatsAppController(message_handler=message_handler)

    messages = [
        Message(
            message_id=1,
            channel=Channel.WHATSAPP,
            created_at=datetime.now(UTC),
            user_id="111",
            chat_id="111",
            content="hello",
        ),
        Message(
            message_id=2,
            channel=Channel.WHATSAPP,
            created_at=datetime.now(UTC),
            user_id="222",
            chat_id="222",
            content="world",
        ),
    ]
    extracted_messages = [_ParsedWhatsAppMessage(message) for message in messages]

    request = MagicMock()
    request.json = AsyncMock(return_value={"entry": []})

    with patch.object(
        controller,
        "_extract_messages",
        return_value=extracted_messages,
    ) as mock_extract_messages:
        result = await controller.receive_webhook(request)

    request.json.assert_awaited_once()
    mock_extract_messages.assert_called_once_with({"entry": []})
    assert message_handler.handle.await_count == 2
    message_handler.handle.assert_any_await(messages[0])
    message_handler.handle.assert_any_await(messages[1])
    assert result == {"status": "ok"}


@pytest.mark.asyncio
async def test_receive_webhook_discards_messages_older_than_ten_minutes() -> None:
    message_handler = MagicMock()
    message_handler.handle = AsyncMock()
    controller = WhatsAppController(message_handler=message_handler)

    stale_message = Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC) - timedelta(minutes=10, seconds=1),
        user_id="111",
        chat_id="111",
        content="old",
    )
    recent_message = Message(
        message_id=2,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC) - timedelta(minutes=9),
        user_id="222",
        chat_id="222",
        content="recent",
    )

    request = MagicMock()
    request.json = AsyncMock(return_value={"entry": []})

    with patch.object(
        controller,
        "_extract_messages",
        return_value=[
            _ParsedWhatsAppMessage(stale_message),
            _ParsedWhatsAppMessage(recent_message),
        ],
    ):
        result = await controller.receive_webhook(request)

    message_handler.handle.assert_awaited_once_with(recent_message)
    assert result == {"status": "ok"}


def test_is_recent_message_discards_messages_without_timestamp() -> None:
    controller = WhatsAppController(message_handler=MagicMock())
    message = Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=None,
        user_id="111",
        chat_id="111",
        content="unknown age",
    )

    assert controller._is_recent_message(message) is False


def test_parse_message_text_returns_expected_message() -> None:
    controller = WhatsAppController(message_handler=MagicMock())

    raw_message = {
        "id": "wamid.abc123",
        "from": "5511999999999",
        "timestamp": "1710000000",
        "type": "text",
        "text": {"body": "oi tudo bem?"},
    }

    result = controller._parse_message(raw_message)

    assert result is not None
    parsed = result.message
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "oi tudo bem?"
    assert parsed.media is None
    assert parsed.created_at == datetime.fromtimestamp(1710000000, tz=UTC)
    assert isinstance(parsed.message_id, int)
    assert parsed.message_id == controller._to_int_message_id("wamid.abc123")


def test_parse_message_button_sets_button_text_as_content() -> None:
    controller = WhatsAppController(message_handler=MagicMock())

    raw_message = {
        "id": "wamid.button123",
        "from": "5511999999999",
        "timestamp": "1710000001",
        "type": "button",
        "button": {"payload": "btn_1", "text": "Quero continuar"},
    }

    result = controller._parse_message(raw_message)

    assert result is not None
    parsed = result.message
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "Quero continuar"
    assert parsed.media is None
    assert parsed.created_at == datetime.fromtimestamp(1710000001, tz=UTC)
    assert isinstance(parsed.message_id, int)
    assert parsed.message_id == controller._to_int_message_id(
        "wamid.button123")


def test_parse_message_interactive_button_reply_sets_title_as_content() -> None:
    controller = WhatsAppController(message_handler=MagicMock())

    raw_message = {
        "id": "wamid.interactive123",
        "from": "5511999999999",
        "timestamp": "1710000002",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "btn_2", "title": "Falar com humano"},
        },
    }

    result = controller._parse_message(raw_message)

    assert result is not None
    parsed = result.message
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "Falar com humano"
    assert parsed.media is None
    assert parsed.created_at == datetime.fromtimestamp(1710000002, tz=UTC)
    assert isinstance(parsed.message_id, int)
    assert parsed.message_id == controller._to_int_message_id(
        "wamid.interactive123")


@pytest.mark.asyncio
async def test_parse_and_resolve_image_stores_only_the_s3_path() -> None:
    s3_service = MagicMock(spec=S3MediaService)
    s3_service.upload_from_whatsapp = AsyncMock(
        return_value="media/image/whatsapp-image.jpg"
    )
    controller = WhatsAppController(
        message_handler=MagicMock(),
        s3_service=s3_service,
    )
    raw_message = {
        "id": "wamid.image123",
        "from": "5511999999999",
        "timestamp": "1710000003",
        "type": "image",
        "image": {"id": "whatsapp-image"},
    }

    parsed = controller._parse_message(raw_message)

    assert parsed is not None
    assert parsed.message.media is None
    assert parsed.media_id == "whatsapp-image"
    assert parsed.media_type == "image"

    resolved = await controller._resolve_media(parsed)

    assert resolved.media == "media/image/whatsapp-image.jpg"
    s3_service.upload_from_whatsapp.assert_awaited_once_with(
        "whatsapp-image",
        "image",
    )


@pytest.mark.asyncio
async def test_parse_and_resolve_video_stores_only_the_s3_path() -> None:
    s3_service = MagicMock(spec=S3MediaService)
    s3_service.upload_from_whatsapp = AsyncMock(
        return_value="media/video/whatsapp-video.mp4"
    )
    controller = WhatsAppController(
        message_handler=MagicMock(),
        s3_service=s3_service,
    )
    raw_message = {
        "id": "wamid.video123",
        "from": "5511999999999",
        "timestamp": "1710000004",
        "type": "video",
        "video": {
            "id": "whatsapp-video",
            "caption": "Vídeo de qualificação",
        },
    }

    parsed = controller._parse_message(raw_message)

    assert parsed is not None
    assert parsed.message.content == "Vídeo de qualificação"
    assert parsed.media_id == "whatsapp-video"
    assert parsed.media_type == "video"

    resolved = await controller._resolve_media(parsed)

    assert resolved.media == "media/video/whatsapp-video.mp4"
    s3_service.upload_from_whatsapp.assert_awaited_once_with(
        "whatsapp-video",
        "video",
    )


def test_parse_media_without_media_id_is_ignored() -> None:
    controller = WhatsAppController(message_handler=MagicMock())

    parsed = controller._parse_message(
        {
            "id": "wamid.invalid-image",
            "from": "5511999999999",
            "timestamp": "1710000004",
            "type": "image",
            "image": {},
        }
    )

    assert parsed is None
