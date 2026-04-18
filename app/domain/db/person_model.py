"""Person ORM model."""

from datetime import datetime
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.domain.enum.channels import Channel
from app.domain.db.base import Base


class PersonModel(Base):
    """Represents a person in the database."""

    __tablename__ = "person"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    cpf: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    channel: Mapped[Channel | None] = mapped_column(Enum(Channel), nullable=True)
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