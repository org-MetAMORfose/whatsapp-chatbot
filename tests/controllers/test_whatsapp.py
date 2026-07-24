from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.controllers.whatsapp_controller import WhatsAppController
from app.domain.enum.channels import Channel
from app.domain.message import Message


@pytest.mark.asyncio
async def test_receive_webhook_forwards_extracted_messages_to_handler() -> None:
    message_handler = MagicMock()
    message_handler.handle = AsyncMock()

    controller = WhatsAppController(message_handler=message_handler)

    extracted_messages = [
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
    message_handler.handle.assert_any_await(extracted_messages[0])
    message_handler.handle.assert_any_await(extracted_messages[1])
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
        return_value=[stale_message, recent_message],
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

    parsed = controller._parse_message(raw_message)

    assert parsed is not None
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "oi tudo bem?"
    assert parsed.image is None
    assert parsed.document is None
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

    parsed = controller._parse_message(raw_message)

    assert parsed is not None
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "Quero continuar"
    assert parsed.image is None
    assert parsed.document is None
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

    parsed = controller._parse_message(raw_message)

    assert parsed is not None
    assert parsed.channel == Channel.WHATSAPP
    assert parsed.user_id == "5511999999999"
    assert parsed.chat_id == "5511999999999"
    assert parsed.content == "Falar com humano"
    assert parsed.image is None
    assert parsed.document is None
    assert parsed.created_at == datetime.fromtimestamp(1710000002, tz=UTC)
    assert isinstance(parsed.message_id, int)
    assert parsed.message_id == controller._to_int_message_id(
        "wamid.interactive123")
