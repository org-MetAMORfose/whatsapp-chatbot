"""Defines the Message class representing a message in the chat."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class Message:
    """Represents a message in the chat."""
    user_id: str
    chat_id: str
    content: str
    origin: Literal["telegram", "whatsapp"]
