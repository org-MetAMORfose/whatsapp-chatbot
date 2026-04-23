from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base

if TYPE_CHECKING:
    from app.domain.db.patient_model import PatientModel
    from app.domain.db.professional_model import ProfessionalModel


class ProfessionalPatientModel(Base):
    """Represents the association between professionals and patients."""

    __tablename__ = "professional_patient"
    __table_args__ = (
        UniqueConstraint(
            "professional_id",
            "patient_id",
            name="uq_professional_patient",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professional.id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patient.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    professional: Mapped["ProfessionalModel"] = relationship(
        "ProfessionalModel",
        back_populates="professional_patients",
    )
    patient: Mapped["PatientModel"] = relationship(
        "PatientModel",
        back_populates="professional_patients",
    )