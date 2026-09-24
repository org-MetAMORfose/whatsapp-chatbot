from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base

if TYPE_CHECKING:
    from app.domain.db.person_model import PersonModel


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
    gender: Mapped[str | None] = mapped_column(String, nullable=True)
    minority_group: Mapped[str | None] = mapped_column(String, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_platform: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    person: Mapped["PersonModel"] = relationship(
        "PersonModel",
        back_populates="professional",
    )
