"""Defines the Professional domain model."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.enum.professional_status import ProfessionalStatus


class Professional(BaseModel):
    """Represents a healthcare professional registration."""

    id: int | None = None
    person_id: int
    area: str
    professional_register: str
    register_type: str
    approach: str | None = None
    background: str | None = None
    video_platform: str | None = None
    email: str | None = None
    status: ProfessionalStatus = ProfessionalStatus.REGISTER_PENDING
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    activated_at: datetime | None = None
    created_at: datetime
