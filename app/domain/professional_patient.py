"""Defines the ProfessionalPatient domain model."""

from pydantic import BaseModel


class ProfessionalPatient(BaseModel):
    """Join table linking professionals to their patients."""

    id: int | None = None
    professional_id: int
    patient_id: int
