"""Application service for managing FAQ knowledge entries."""

from datetime import UTC, datetime

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.services.openai_service import OpenAIService


class FaqKnowledgeService:
    """Create FAQ entries with embeddings generated from their questions."""

    def __init__(
        self,
        repository: FaqKnowledgeRepository,
        openai_service: OpenAIService | None = None,
    ) -> None:
        self.repository = repository
        self.openai_service = openai_service or OpenAIService()

    async def create_entry(
        self,
        *,
        question: str,
        answer: str,
    ) -> FaqKnowledgeEntryModel:
        normalized_question = question.strip()
        normalized_answer = answer.strip()
        if not normalized_question or not normalized_answer:
            raise ValueError("Question and answer must not be blank.")

        embedding = await self.openai_service.generate_embedding(
            normalized_question
        )
        return self.repository.create(
            question=normalized_question,
            answer=normalized_answer,
            embedding=embedding.embedding,
            embedding_model=embedding.model,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
