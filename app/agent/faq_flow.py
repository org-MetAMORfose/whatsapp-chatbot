"""Retrieval-augmented FAQ question processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

import app.config.settings as config
from app.domain.db.faq_interaction_model import FaqInteractionModel
from app.domain.db.faq_session_model import FaqSessionModel
from app.domain.enum.faq_answer_status import FaqAnswerStatus
from app.domain.message import Message
from app.repository.sql.faq_knowledge_repository import (
    FaqKnowledgeCandidate,
    FaqKnowledgeRepository,
)
from app.repository.sql.faq_session_repository import FaqSessionRepository
from app.repository.sql.person_repository import PersonRepository
from app.services.openai_service import (
    OpenAIEmbeddingResult,
    OpenAIFaqSelectionResult,
    OpenAIService,
)

FAQ_NOT_FOUND_MESSAGE = (
    "Não encontrei uma resposta adequada para essa dúvida. "
    "Você pode reformular a pergunta ou solicitar atendimento humano."
)


@dataclass(frozen=True)
class FaqFlowResult:
    content: str
    session_id: int
    interaction_id: int
    selected_entry_id: int | None


class FaqFlow:
    """Coordinate one FAQ question from session lookup through persistence."""

    def __init__(
        self,
        *,
        person_repository: PersonRepository,
        session_repository: FaqSessionRepository,
        knowledge_repository: FaqKnowledgeRepository,
        openai_service: OpenAIService | None = None,
        retrieval_limit: int | None = None,
    ) -> None:
        self.person_repository = person_repository
        self.session_repository = session_repository
        self.knowledge_repository = knowledge_repository
        self.openai_service = openai_service or OpenAIService()
        self.retrieval_limit = (
            config.FAQ_RETRIEVAL_LIMIT
            if retrieval_limit is None
            else retrieval_limit
        )

    async def process(self, message: Message) -> FaqFlowResult:
        """Process a FAQ question.

        The orchestration deliberately delegates validation, session lifecycle,
        retrieval, model selection, and persistence to focused helpers so the
        main path remains linear and each stage can be tested independently.
        """
        question, history_id = self._validate_message(message)
        started_at = perf_counter()
        faq_session = self._get_session(message)
        embedding = await self.openai_service.generate_embedding(question)
        candidates = self._find_candidates(embedding)
        if not candidates:
            return self._record_not_found(
                faq_session=faq_session,
                history_id=history_id,
                embedding=embedding,
                started_at=started_at,
            )

        selection = await self.openai_service.select_faq_answer(
            question=question,
            candidates=candidates,
        )
        return self._record_selection(
            faq_session=faq_session,
            history_id=history_id,
            embedding=embedding,
            candidates=candidates,
            selection=selection,
            started_at=started_at,
        )

    @staticmethod
    def _validate_message(message: Message) -> tuple[str, int]:
        question = (message.content or "").strip()
        if not question:
            raise ValueError("FAQ processing requires a text question.")
        if message.history_id is None:
            raise ValueError("FAQ processing requires a message history id.")
        return question, message.history_id

    def _get_session(self, message: Message) -> FaqSessionModel:
        person = self.person_repository.get_by_phone_number_and_channel(
            message.user_id,
            message.channel,
        )
        if person is None:
            raise ValueError("The message person was not found.")
        return self.session_repository.get_or_create_active(
            person_id=person.id,
            now=_utcnow(),
        )

    def _find_candidates(
        self,
        embedding: OpenAIEmbeddingResult,
    ) -> list[FaqKnowledgeCandidate]:
        return self.knowledge_repository.find_similar(
            embedding=embedding.embedding,
            embedding_model=embedding.model,
            limit=self.retrieval_limit,
        )

    def _record_not_found(
        self,
        *,
        faq_session: FaqSessionModel,
        history_id: int,
        embedding: OpenAIEmbeddingResult,
        started_at: float,
    ) -> FaqFlowResult:
        interaction = self._record_interaction(
            faq_session=faq_session,
            history_id=history_id,
            selected_entry_id=None,
            answer_status=FaqAnswerStatus.NOT_FOUND,
            similarity_score=None,
            input_tokens=embedding.input_tokens,
            output_tokens=0,
            started_at=started_at,
        )
        return self._to_result(interaction, FAQ_NOT_FOUND_MESSAGE)

    def _record_selection(
        self,
        *,
        faq_session: FaqSessionModel,
        history_id: int,
        embedding: OpenAIEmbeddingResult,
        candidates: list[FaqKnowledgeCandidate],
        selection: OpenAIFaqSelectionResult,
        started_at: float,
    ) -> FaqFlowResult:
        selected = self._selected_candidate(candidates, selection.selected_entry_id)
        answer_status = None if selected is not None else FaqAnswerStatus.NOT_FOUND
        interaction = self._record_interaction(
            faq_session=faq_session,
            history_id=history_id,
            selected_entry_id=selected.entry_id if selected is not None else None,
            answer_status=answer_status,
            similarity_score=(
                selected.similarity_score if selected is not None else None
            ),
            input_tokens=embedding.input_tokens + selection.input_tokens,
            output_tokens=selection.output_tokens,
            started_at=started_at,
        )
        content = selected.answer if selected is not None else FAQ_NOT_FOUND_MESSAGE
        return self._to_result(interaction, content)

    def _record_interaction(
        self,
        *,
        faq_session: FaqSessionModel,
        history_id: int,
        selected_entry_id: int | None,
        answer_status: FaqAnswerStatus | None,
        similarity_score: float | None,
        input_tokens: int,
        output_tokens: int,
        started_at: float,
    ) -> FaqInteractionModel:
        return self.session_repository.record_interaction(
            session_id=faq_session.id,
            question_message_id=history_id,
            selected_entry_id=selected_entry_id,
            answer_status=answer_status,
            similarity_score=similarity_score,
            latency_ms=round((perf_counter() - started_at) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            created_at=_utcnow(),
        )

    @staticmethod
    def _selected_candidate(
        candidates: list[FaqKnowledgeCandidate],
        selected_entry_id: int | None,
    ) -> FaqKnowledgeCandidate | None:
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.entry_id == selected_entry_id
            ),
            None,
        )

    @staticmethod
    def _to_result(
        interaction: FaqInteractionModel,
        content: str,
    ) -> FaqFlowResult:
        return FaqFlowResult(
            content=content,
            session_id=interaction.session_id,
            interaction_id=interaction.id,
            selected_entry_id=interaction.selected_entry_id,
        )


def _utcnow() -> datetime:
    """Return UTC in the naive format used by the existing database columns."""
    return datetime.now(UTC).replace(tzinfo=None)
