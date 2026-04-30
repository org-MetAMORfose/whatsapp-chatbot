from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.enum.professional_status import ProfessionalStatus

if TYPE_CHECKING:
    from app.domain.db.professional_model import ProfessionalModel


class ProfessionalStatusHistoryModel(Base):
    """Represents a professional status change in the database."""

    __tablename__ = "professional_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    professional_id: Mapped[int] = mapped_column(
        ForeignKey("professional.id", ondelete="CASCADE"),
        nullable=False,
    )
    professional_status: Mapped[ProfessionalStatus] = mapped_column(
        Enum(ProfessionalStatus),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    professional: Mapped["ProfessionalModel"] = relationship(
        "ProfessionalModel",
        back_populates="status_history",
        foreign_keys=[professional_id],
    )