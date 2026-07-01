from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base

if TYPE_CHECKING:
    from app.domain.db.patient_model import PatientModel
    from app.domain.db.person_model import PersonModel
    from app.domain.db.professional_patient_model import ProfessionalPatientModel
    from app.domain.db.professional_status_history_model import (
        ProfessionalStatusHistoryModel,
    )


class ProfessionalModel(Base):
    """Represents a professional in the database."""

    __tablename__ = "professional"
    __table_args__ = (
        UniqueConstraint(
            "register_type",
            "professional_register",
            name="uq_professional_register",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    area: Mapped[str] = mapped_column(String, nullable=False)
    professional_register: Mapped[str] = mapped_column(String, nullable=False)
    register_type: Mapped[str] = mapped_column(String, nullable=False)
    approach: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_platform: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    person: Mapped["PersonModel"] = relationship(
        "PersonModel",
        back_populates="professional",
    )

    status_history: Mapped[list["ProfessionalStatusHistoryModel"]] = relationship(
        "ProfessionalStatusHistoryModel",
        back_populates="professional",
        foreign_keys="ProfessionalStatusHistoryModel.professional_id",
        cascade="all, delete-orphan",
        order_by=(
            "ProfessionalStatusHistoryModel.created_at,"
            "ProfessionalStatusHistoryModel.id"
        ),
    )

    @property
    def current_status(self) -> "ProfessionalStatusHistoryModel":
        """Return the most recent status history entry."""
        if not self.status_history:
            raise RuntimeError("Professional has no status history.")

        return self.status_history[-1]

    professional_patients: Mapped[list["ProfessionalPatientModel"]] = relationship(
        "ProfessionalPatientModel",
        back_populates="professional",
        cascade="all, delete-orphan",
    )

    patients: Mapped[list["PatientModel"]] = relationship(
        "PatientModel",
        secondary="professional_patient",
        back_populates="professionals",
        viewonly=True,
    )
