"""Defines the Message class representing a message in the chat."""

from dataclasses import dataclass

from app.domain.channels import Channel


@dataclass
class Message:
    """Represents a message in the chat."""

    channel: Channel
    user_id: str
    chat_id: str
    content: str
