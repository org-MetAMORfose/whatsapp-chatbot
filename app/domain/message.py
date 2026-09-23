"""Defines the Message class representing a message in the chat."""

from datetime import UTC, datetime
from typing import TypedDict

from pydantic import BaseModel

from app.domain.enum.channels import Channel


class MessageButton(TypedDict):
    """Represents a button in a message."""

    id: str
    title: str


class Message(BaseModel):
    """Represents a message in the chat."""

    event_id: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    message_id: int
    channel: Channel
    created_at: datetime | None
    user_id: str
    chat_id: str
    content: str | None
    pressed: int | None = None
    history_id: int | None = None

    media: str | None = None
    buttons: list[MessageButton] | None = None

    def is_recent(self, now: datetime | None = None) -> bool:
        if self.created_at is None:
            return False
        timestamp = self.created_at.replace(tzinfo=UTC) if self.created_at.tzinfo is None else self.created_at
        age = ((now or datetime.now(UTC)) - timestamp).total_seconds()
        return 0 <= age <= 300
