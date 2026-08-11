"""FAQ knowledge entry ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base

if TYPE_CHECKING:
    from app.domain.db.faq_interaction_model import FaqInteractionModel


class FaqKnowledgeEntryModel(Base):
    """Represents an official question and answer used by semantic search."""

    __tablename__ = "faq_knowledge_entry"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Identificador único da entrada da base de conhecimento.",
    )
    question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Pergunta de referência usada para gerar o embedding.",
    )
    answer: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Resposta oficial associada à pergunta de referência.",
    )
    embedding: Mapped[list[float]] = mapped_column(
        VECTOR(),
        nullable=False,
        comment="Vetor semântico da pergunta; a dimensão depende do modelo informado.",
    )
    embedding_model: Mapped[str] = mapped_column(
        String,
        nullable=False,
        comment="Modelo usado para gerar o embedding e determinar sua dimensão.",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="Data do soft delete; entradas preenchidas não devem participar da busca.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="Data e hora de criação da entrada de conhecimento.",
    )

    selected_interactions: Mapped[list["FaqInteractionModel"]] = relationship(
        "FaqInteractionModel",
        back_populates="selected_entry",
    )
