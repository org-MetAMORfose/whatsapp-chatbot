"""Temporary patient registration context stored in Redis."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.domain.enum.channels import Channel


class PatientStageContext(BaseModel):
    """Represents an in-progress patient registration."""

    user_id: str
    chat_id: str
    channel: Channel

    name: str | None = None
    birth_date: date | None = None
    area: str | None = None
    psychotherapy_approach: str | None = None
    professional_profile: str | None = None
    psychotherapy_specialties: list[str] | None = None
    preferred_gender: str | None = None
    preferred_race: str | None = None
    prefers_lgbtqiapn_plus: bool | None = None
    price_range: str | None = None
    is_returning: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
