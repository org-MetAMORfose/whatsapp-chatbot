"""Defines the Patient domain model."""

from datetime import datetime

from pydantic import BaseModel


class Patient(BaseModel):
    """Represents a patient linked to a person record."""

    id: int | None = None
    person_id: int
    created_at: datetime
