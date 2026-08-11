"""FAQ session ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.enum.faq_session_outcome import FaqSessionOutcome

if TYPE_CHECKING:
    from app.domain.db.faq_interaction_model import FaqInteractionModel
    from app.domain.db.person_model import PersonModel


class FaqSessionModel(Base):
    """Represents one person's entry into the FAQ flow."""

    __tablename__ = "faq_session"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Identificador único da sessão de FAQ.",
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id"),
        nullable=False,
        comment="Pessoa que iniciou o fluxo de dúvidas.",
    )
    outcome: Mapped[FaqSessionOutcome] = mapped_column(
        Enum(FaqSessionOutcome, name="faq_session_outcome"),
        nullable=False,
        default=FaqSessionOutcome.ACTIVE,
        server_default=FaqSessionOutcome.ACTIVE.value,
        comment="Resultado atual ou final da sessão.",
    )
    question_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Quantidade de perguntas feitas durante a sessão.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="Data e hora em que a sessão foi iniciada.",
    )

    person: Mapped["PersonModel"] = relationship("PersonModel")
    interactions: Mapped[list["FaqInteractionModel"]] = relationship(
        "FaqInteractionModel",
        back_populates="session",
        order_by="(FaqInteractionModel.question_number, FaqInteractionModel.id)",
        cascade="all, delete-orphan",
    )
