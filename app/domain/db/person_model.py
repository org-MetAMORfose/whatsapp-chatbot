"""Person ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.enum.channels import Channel

if TYPE_CHECKING:
    from app.domain.db.message_history_model import MessageHistoryModel
    from app.domain.db.patient_model import PatientModel
    from app.domain.db.professional_model import ProfessionalModel


class PersonModel(Base):
    """Represents a person in the database."""

    __tablename__ = "person"

    __table_args__ = (
        UniqueConstraint("phone_number", "channel", name="uq_person_phone_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[Channel | None] = mapped_column(Enum(Channel), nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    cpf: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    chat_state: Mapped[str] = mapped_column(String, nullable=False, default="START")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    professional: Mapped["ProfessionalModel"] = relationship(
        "ProfessionalModel", back_populates="person", uselist=False
    )
    patient: Mapped["PatientModel"] = relationship(
        "PatientModel", back_populates="person", uselist=False
    )
    messages: Mapped[list["MessageHistoryModel"]] = relationship(
        "MessageHistoryModel",
        back_populates="person",
        order_by="(MessageHistoryModel.created_at, MessageHistoryModel.id)",
    )
