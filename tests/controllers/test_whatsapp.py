from datetime import UTC, datetime
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


def test_parse_message_text_returns_expected_message() -> None:
    controller = WhatsAppController(message_handler=MagicMock())

    raw_message = {
        "id": "wamid.abc123",
        "from": "5511999999999",
        "timestamp": "1710000000",
        "type": "text",
        "text": {
            "body": "oi tudo bem?"
        },
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