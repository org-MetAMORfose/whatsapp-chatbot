from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.enum.professional_status import ProfessionalStatus


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
    status: Mapped[ProfessionalStatus] = mapped_column(
        Enum(ProfessionalStatus),
        nullable=False,
        default=ProfessionalStatus.REGISTER_PENDING,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    person: Mapped["PersonModel"] = relationship(
        "PersonModel",
        back_populates="professional",
    )

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