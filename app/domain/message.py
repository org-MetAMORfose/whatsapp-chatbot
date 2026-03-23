"""Defines the Message class representing a message in the chat."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.channels import Channel


@dataclass
class Message:
    """Represents a message in the chat."""

    message_id: int
    channel: Channel
    created_at: datetime
    user_id: str
    chat_id: str
    content: str


@dataclass
class UserMessage:
    """Represents a message sent by the user."""

    message_id: int
    channel: Channel
    created_at: datetime
    user_id: str
    chat_id: str
    content: str


@dataclass
class BotMessage:
    """Represents a message sent by the bot."""

    message_id: int
    channel: Channel
    created_at: datetime
    chat_id: str
    content: str
