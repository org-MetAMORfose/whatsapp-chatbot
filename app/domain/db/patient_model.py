from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.db.delivery_model import JSON_TYPE

if TYPE_CHECKING:
    from app.domain.db.person_model import PersonModel


class PatientModel(Base):
    """Represents a patient in the database."""

    __tablename__ = "patient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE"),
        nullable=False,
    )
    area: Mapped[str | None] = mapped_column(String, nullable=True)
    psychotherapy_approach: Mapped[str | None] = mapped_column(String, nullable=True)
    professional_profile: Mapped[str | None] = mapped_column(String, nullable=True)
    matching_request: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, default=dict, nullable=False)
    price_range: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    person: Mapped["PersonModel"] = relationship(
        "PersonModel",
        back_populates="patients",
        lazy="joined",
    )
