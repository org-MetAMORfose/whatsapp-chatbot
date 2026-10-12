from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message
from app.infra.message_queue import Delivery
from app.services.inbound_processor import InboundProcessor
from app.services.whatsapp_media_service import DownloadedMedia


@pytest.mark.asyncio
async def test_inbound_audio_is_uploaded_and_persisted_as_media_path() -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    stored_history = MagicMock(id=10, media_path=None)
    session.get.side_effect = [None, stored_history]

    people = MagicMock()
    people.get_or_create_person.return_value = PersonModel(
        id=1,
        phone_number="5511999991111",
        channel=Channel.WHATSAPP,
        chat_mode=ChatMode.MANUAL,
    )
    people.create_message.return_value = stored_history

    media = MagicMock()
    media.upload_file = AsyncMock(return_value="media/audio/voice-note.ogg")
    inbound = MagicMock()
    inbound.complete_inbound = AsyncMock()
    follow_ups = MagicMock()
    follow_ups.consume = AsyncMock(return_value=False)
    processor = InboundProcessor(
        factory,
        MagicMock(),
        people,
        inbound,
        MagicMock(),
        media,
        follow_ups,
    )
    message = Message(
        event_id="whatsapp:audio-1",
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime.now(UTC),
        user_id="5511999991111",
        chat_id="5511999991111",
        content=None,
        media_id="whatsapp-audio-id",
        media_type="audio",
    )
    downloader = MagicMock()
    downloader.download = AsyncMock(
        return_value=DownloadedMedia(b"audio-bytes", "audio/ogg")
    )

    with patch(
        "app.services.inbound_processor.WhatsAppMediaService",
        return_value=downloader,
    ):
        await processor.process(
            Delivery("delivery-1", message.model_dump_json(), 1)
        )

    downloader.download.assert_awaited_once_with("whatsapp-audio-id")
    media.upload_file.assert_awaited_once_with(
        b"audio-bytes",
        "audio/ogg",
        "audio",
    )
    persisted_message = people.create_message.call_args.args[0]
    assert persisted_message.media_path == "media/audio/voice-note.ogg"
    assert stored_history.media_path == "media/audio/voice-note.ogg"
