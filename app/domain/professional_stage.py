"""Temporary professional registration context stored in Redis."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enum.channels import Channel


class ProfessionalStageContext(BaseModel):
    """Represents an in-progress professional registration."""

    user_id: str
    chat_id: str
    channel: Channel

    qualification: str | None = None
    video_tool: str | None = None
    council_registration: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)