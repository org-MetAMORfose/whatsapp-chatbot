"""SQL repository for the FAQ knowledge base."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel


@dataclass(frozen=True)
class FaqKnowledgeCandidate:
    """FAQ entry returned by semantic search with its similarity score."""

    entry_id: int
    question: str
    answer: str
    similarity_score: float


class FaqKnowledgeRepository:
    """Persist FAQ entries and perform vector similarity searches."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        question: str,
        answer: str,
        embedding: Sequence[float],
        embedding_model: str,
        created_at: datetime,
    ) -> FaqKnowledgeEntryModel:
        entry = FaqKnowledgeEntryModel(
            question=question,
            answer=answer,
            embedding=list(embedding),
            embedding_model=embedding_model,
            created_at=created_at,
        )

        with self._session_factory() as session:
            session.add(entry)
            session.commit()
            session.refresh(entry)
            return entry

    def get_by_id(self, entry_id: int) -> FaqKnowledgeEntryModel | None:
        with self._session_factory() as session:
            return session.get(FaqKnowledgeEntryModel, entry_id)

    def find_similar(
        self,
        *,
        embedding: Sequence[float],
        embedding_model: str,
        limit: int,
    ) -> list[FaqKnowledgeCandidate]:
        """Return active entries ordered by cosine similarity."""
        distance = FaqKnowledgeEntryModel.embedding.cosine_distance(
            list(embedding)
        ).label("distance")
        stmt = (
            select(FaqKnowledgeEntryModel, distance)
            .where(
                FaqKnowledgeEntryModel.deleted_at.is_(None),
                FaqKnowledgeEntryModel.embedding_model == embedding_model,
            )
            .order_by(distance)
            .limit(limit)
        )

        with self._session_factory() as session:
            rows = session.execute(stmt).all()

        return [
            FaqKnowledgeCandidate(
                entry_id=entry.id,
                question=entry.question,
                answer=entry.answer,
                similarity_score=1.0 - float(cosine_distance),
            )
            for entry, cosine_distance in rows
        ]
