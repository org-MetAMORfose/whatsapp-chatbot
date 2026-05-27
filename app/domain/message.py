"""Defines the Message class representing a message in the chat."""

from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel

from app.domain.enum.channels import Channel


class MessageButton(TypedDict):
    """Represents a button in a message."""

    id: str
    title: str


class Message(BaseModel):
    """Represents a message in the chat."""

    message_id: int
    channel: Channel
    created_at: datetime | None
    user_id: str
    chat_id: str
    content: str | None
    pressed: int | None = None

    image: str | None = None
    document: str | None = None
    buttons: list[MessageButton] | None = None
