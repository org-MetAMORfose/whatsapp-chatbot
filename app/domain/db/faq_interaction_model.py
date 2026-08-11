"""FAQ interaction ORM model."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.db.base import Base
from app.domain.enum.faq_answer_status import FaqAnswerStatus

if TYPE_CHECKING:
    from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
    from app.domain.db.faq_session_model import FaqSessionModel
    from app.domain.db.message_history_model import MessageHistoryModel


class FaqInteractionModel(Base):
    """Represents one user question processed during a FAQ session."""

    __tablename__ = "faq_interaction"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
        comment="Identificador único da interação de FAQ.",
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("faq_session.id"),
        nullable=False,
        comment="Sessão de FAQ em que a pergunta ocorreu.",
    )
    question_message_id: Mapped[int] = mapped_column(
        ForeignKey("message_history.id"),
        nullable=False,
        comment="Mensagem original do usuário que contém o texto da pergunta.",
    )
    selected_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("faq_knowledge_entry.id"),
        nullable=True,
        comment="Entrada escolhida pelo RAG; nula quando nenhuma resposta for adequada.",
    )
    question_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Posição ordinal da pergunta dentro da sessão.",
    )
    answer_status: Mapped[FaqAnswerStatus | None] = mapped_column(
        Enum(FaqAnswerStatus, name="faq_answer_status"),
        nullable=True,
        comment="Resultado observado para a resposta desta interação.",
    )
    similarity_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="Similaridade da entrada selecionada com a pergunta do usuário.",
    )
    latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Tempo total de processamento da interação em milissegundos.",
    )
    input_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Quantidade de tokens enviados ao modelo de IA.",
    )
    output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Quantidade de tokens gerados pelo modelo de IA.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        comment="Data e hora em que a pergunta foi processada.",
    )

    session: Mapped["FaqSessionModel"] = relationship(
        "FaqSessionModel",
        back_populates="interactions",
    )
    question_message: Mapped["MessageHistoryModel"] = relationship("MessageHistoryModel")
    selected_entry: Mapped["FaqKnowledgeEntryModel | None"] = relationship(
        "FaqKnowledgeEntryModel",
        back_populates="selected_interactions",
    )
