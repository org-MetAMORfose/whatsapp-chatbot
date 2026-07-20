"""Temporary patient registration context stored in Redis."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enum.channels import Channel


class PatientStageContext(BaseModel):
    """Represents an in-progress patient registration."""

    user_id: str
    chat_id: str
    channel: Channel

    name: str | None = None
    area: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
