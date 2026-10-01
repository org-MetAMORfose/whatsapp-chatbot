"""Application service for managing FAQ knowledge entries."""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.repository.sql.faq_knowledge_repository import (
    FaqKnowledgeEntryCreate,
    FaqKnowledgeRepository,
)
from app.services.openai_service import OpenAIService


class FaqKnowledgeGroupNotFoundError(LookupError):
    """Raised when an active FAQ group cannot be found."""


class FaqKnowledgeEntryNotFoundError(LookupError):
    """Raised when an active FAQ question cannot be found."""


@dataclass(frozen=True)
class FaqKnowledgeGroup:
    """Active FAQ entries that share the exact same official answer."""

    id: int
    answer: str
    questions: list[FaqKnowledgeEntryModel]


class FaqKnowledgeService:
    """Manage FAQ groups and generate embeddings for new questions."""

    def __init__(
        self,
        repository: FaqKnowledgeRepository,
        openai_service: OpenAIService | None = None,
    ) -> None:
        self.repository = repository
        self.openai_service = openai_service or OpenAIService()

    def list_groups(self) -> list[FaqKnowledgeGroup]:
        return self._group_entries(self.repository.list_active())

    async def create_entry(
        self,
        *,
        question: str,
        answer: str,
    ) -> FaqKnowledgeEntryModel:
        normalized_question = self._normalize_required(question, "Question")
        normalized_answer = self._normalize_required(answer, "Answer")
        embedding = await self.openai_service.generate_embedding(
            normalized_question
        )
        return self.repository.create(
            question=normalized_question,
            answer=normalized_answer,
            embedding=embedding.embedding,
            embedding_model=embedding.model,
            created_at=self._now(),
        )

    async def create_group(
        self,
        *,
        questions: list[str],
        answer: str,
    ) -> FaqKnowledgeGroup:
        normalized_answer = self._normalize_required(answer, "Answer")
        normalized_questions = self._normalize_questions(questions)
        entries: list[FaqKnowledgeEntryCreate] = []
        for question in normalized_questions:
            embedding = await self.openai_service.generate_embedding(question)
            entries.append(
                FaqKnowledgeEntryCreate(
                    question=question,
                    answer=normalized_answer,
                    embedding=embedding.embedding,
                    embedding_model=embedding.model,
                )
            )
        created = self.repository.create_group(
            entries=entries,
            created_at=self._now(),
        )
        return self._group_entries(created)[0]

    async def add_question(
        self,
        *,
        group_entry_id: int,
        question: str,
    ) -> FaqKnowledgeGroup:
        normalized_question = self._normalize_required(question, "Question")
        if self.repository.get_active_by_id(group_entry_id) is None:
            raise FaqKnowledgeGroupNotFoundError("FAQ group not found.")
        embedding = await self.openai_service.generate_embedding(
            normalized_question
        )
        created = self.repository.add_question(
            group_entry_id=group_entry_id,
            question=normalized_question,
            embedding=embedding.embedding,
            embedding_model=embedding.model,
            created_at=self._now(),
        )
        if created is None:
            raise FaqKnowledgeGroupNotFoundError("FAQ group not found.")
        group_entries = [
            entry
            for entry in self.repository.list_active()
            if entry.answer == created.answer
        ]
        return self._group_entries(group_entries)[0]

    def update_group_answer(
        self,
        *,
        group_entry_id: int,
        answer: str,
    ) -> FaqKnowledgeGroup:
        normalized_answer = self._normalize_required(answer, "Answer")
        entries = self.repository.update_group_answer(
            group_entry_id=group_entry_id,
            answer=normalized_answer,
        )
        if entries is None:
            raise FaqKnowledgeGroupNotFoundError("FAQ group not found.")
        return self._group_entries(entries)[0]

    def delete_question(self, *, entry_id: int) -> None:
        if not self.repository.soft_delete_entry(
            entry_id=entry_id,
            deleted_at=self._now(),
        ):
            raise FaqKnowledgeEntryNotFoundError("FAQ question not found.")

    def delete_group(self, *, group_entry_id: int) -> int:
        deleted_count = self.repository.soft_delete_group(
            group_entry_id=group_entry_id,
            deleted_at=self._now(),
        )
        if deleted_count is None:
            raise FaqKnowledgeGroupNotFoundError("FAQ group not found.")
        return deleted_count

    @staticmethod
    def _normalize_required(value: str, field: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} must not be blank.")
        return normalized

    @classmethod
    def _normalize_questions(cls, questions: list[str]) -> list[str]:
        if not questions:
            raise ValueError("At least one question is required.")
        normalized = [
            cls._normalize_required(question, "Question")
            for question in questions
        ]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Questions in the same group must be unique.")
        return normalized

    @staticmethod
    def _group_entries(
        entries: list[FaqKnowledgeEntryModel],
    ) -> list[FaqKnowledgeGroup]:
        grouped: dict[str, list[FaqKnowledgeEntryModel]] = {}
        for entry in entries:
            grouped.setdefault(entry.answer, []).append(entry)
        return [
            FaqKnowledgeGroup(
                id=min(entry.id for entry in questions),
                answer=answer,
                questions=sorted(
                    questions,
                    key=lambda entry: (entry.created_at, entry.id),
                ),
            )
            for answer, questions in grouped.items()
        ]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
