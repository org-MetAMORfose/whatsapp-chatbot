"""Immediate care request: a Pix-paid session offered to available psychologists, first to accept wins."""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.db.delivery_model import utcnow
from app.domain.enum.immediate_status import ImmediateStatus

if TYPE_CHECKING:
    from app.domain.db.person_model import PersonModel


class ImmediateRequestModel(Base):
    __tablename__ = "immediate_request"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_payment', 'queued', 'accepted', 'expired', 'cancelled')",
            name="ck_immediate_request_status",
        ),
        Index("ix_immediate_request_status_expires", "status", "expires_at"),
        Index("ix_immediate_request_patient", "patient_person_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), nullable=False)
    professional_person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=ImmediateStatus.AWAITING_PAYMENT.value)
    pix_txid: Mapped[str | None] = mapped_column(String, unique=True)
    pix_copia_cola: Mapped[str | None] = mapped_column(Text)
    pix_e2e_id: Mapped[str | None] = mapped_column(String)
    pix_refund_id: Mapped[str | None] = mapped_column(String)
    room_url: Mapped[str | None] = mapped_column(Text)  # the room itself, without a token: it does not let anyone in
    patient_room_url: Mapped[str | None] = mapped_column(Text)  # join links with each person's token, sent only by WhatsApp
    professional_room_url: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    patient: Mapped["PersonModel"] = relationship("PersonModel", foreign_keys=[patient_person_id], lazy="joined")
    professional: Mapped["PersonModel | None"] = relationship("PersonModel", foreign_keys=[professional_person_id], lazy="joined")
