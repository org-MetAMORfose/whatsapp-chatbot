"""MessageHistory ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base

if TYPE_CHECKING:
    from app.domain.db.person_model import PersonModel


class MessageHistoryModel(Base):
    """Represents a message in the conversation history."""

    __tablename__ = "message_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("person.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    document_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_from_user: Mapped[bool] = mapped_column(Boolean, nullable=False)

    person: Mapped["PersonModel"] = relationship("PersonModel", back_populates="messages")
