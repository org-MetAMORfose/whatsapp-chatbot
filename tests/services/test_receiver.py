from datetime import UTC, datetime, timedelta

from app.domain.enum.channels import Channel
from app.domain.message import Message


def test_message_age_boundaries() -> None:
    now = datetime.now(UTC)
    message = Message(message_id=1, created_at=now, channel=Channel.WHATSAPP, chat_id="1", user_id="1", content="hi")
    assert message.is_recent(now)
    assert message.model_copy(update={"created_at": now - timedelta(seconds=300)}).is_recent(now)
    assert not message.model_copy(update={"created_at": now - timedelta(seconds=301)}).is_recent(now)
    assert not message.model_copy(update={"created_at": None}).is_recent(now)
    assert not message.model_copy(update={"created_at": now + timedelta(seconds=1)}).is_recent(now)
