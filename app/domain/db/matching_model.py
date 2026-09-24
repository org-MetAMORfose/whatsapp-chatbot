"""Matching allocation ledger. Capacity is validated by the matching service under row locks."""
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.db.base import Base
from app.domain.db.delivery_model import JSON_TYPE, utcnow


class MatchingCycleModel(Base):
    __tablename__ = "matching_cycle"
    __table_args__ = (
        CheckConstraint("promised_patients > 0", name="ck_matching_capacity"),
        CheckConstraint("deadline_at > starts_at", name="ck_matching_dates"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    professional_id: Mapped[int] = mapped_column(ForeignKey("professional.id"), nullable=False)
    type: Mapped[str] = mapped_column(Enum("REGULAR", "REPLACEMENT", name="matching_cycle_type"), nullable=False)
    promised_patients: Mapped[int] = mapped_column(Integer, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MatchingSlotModel(Base):
    __tablename__ = "matching_slot"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("matching_cycle.id"), nullable=False, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient.id"), nullable=False, unique=True)
    compatibility_score: Mapped[float] = mapped_column(Float, nullable=False)
    urgency_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
