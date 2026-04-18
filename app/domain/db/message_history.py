"""Defines the MessageHistory domain model."""

from datetime import datetime

from pydantic import BaseModel


class MessageHistory(BaseModel):
    """Represents a single message stored in the conversation history."""

    id: int | None = None
    person_id: int
    created_at: datetime
    content: str | None = None
    image_url: str | None = None
    document_url: str | None = None
    is_from_user: bool
