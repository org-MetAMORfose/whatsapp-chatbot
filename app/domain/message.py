"""Defines the Message class representing a message in the chat."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.channels import Channel


class Message(BaseModel):
    """Represents a message in the chat."""

    message_id: int
    channel: Channel
    created_at: datetime | None
    user_id: str
    chat_id: str
    content: str | None

    image: str | None = None
    document: str | None = None
