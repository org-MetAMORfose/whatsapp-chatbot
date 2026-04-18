from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base


class PatientModel(Base):
    """Represents a patient in the database."""

    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    person: Mapped["PersonModel"] = relationship(
        "PersonModel",
        back_populates="patient",
        lazy="joined",
    )

    professional_patients: Mapped[list["ProfessionalPatientModel"]] = relationship(
        "ProfessionalPatientModel",
        back_populates="patient",
        cascade="all, delete-orphan",
    )

    professionals: Mapped[list["ProfessionalModel"]] = relationship(
        "ProfessionalModel",
        secondary="professional_patient",
        back_populates="patients",
        viewonly=True,
    )