"""Temporary professional registration context stored in Redis."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enum.channels import Channel


class ProfessionalStageContext(BaseModel):
    """Represents an in-progress professional registration."""

    user_id: str
    chat_id: str
    channel: Channel

    name: str | None = None
    area: str | None = None
    qualification: str | None = None
    disponibility: str | None = None
    video_tool: str | None = None
    council_registration: str | None = None
    gender: str | None = None
    minority_group: str | None = None
    approach: str | None = None
    council_registration_document: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)