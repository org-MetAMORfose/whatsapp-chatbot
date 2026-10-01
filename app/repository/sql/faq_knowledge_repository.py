"""SQL repository for the FAQ knowledge base."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.repository.sql.transaction import commit, session_scope


@dataclass(frozen=True)
class FaqKnowledgeCandidate:
    """FAQ entry returned by semantic search with its similarity score."""

    entry_id: int
    question: str
    answer: str
    similarity_score: float


@dataclass(frozen=True)
class FaqKnowledgeEntryCreate:
    """Values required to persist one FAQ knowledge entry."""

    question: str
    answer: str
    embedding: Sequence[float]
    embedding_model: str


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
        return self.create_group(
            entries=[
                FaqKnowledgeEntryCreate(
                    question=question,
                    answer=answer,
                    embedding=embedding,
                    embedding_model=embedding_model,
                )
            ],
            created_at=created_at,
        )[0]

    def create_group(
        self,
        *,
        entries: Sequence[FaqKnowledgeEntryCreate],
        created_at: datetime,
    ) -> list[FaqKnowledgeEntryModel]:
        models = [
            FaqKnowledgeEntryModel(
                question=entry.question,
                answer=entry.answer,
                embedding=list(entry.embedding),
                embedding_model=entry.embedding_model,
                created_at=created_at,
            )
            for entry in entries
        ]
        with session_scope(self._session_factory) as session:
            session.add_all(models)
            commit(session)
            for model in models:
                session.refresh(model)
            return models

    def list_active(self) -> list[FaqKnowledgeEntryModel]:
        stmt = (
            select(FaqKnowledgeEntryModel)
            .where(FaqKnowledgeEntryModel.deleted_at.is_(None))
            .order_by(
                FaqKnowledgeEntryModel.answer,
                FaqKnowledgeEntryModel.created_at,
                FaqKnowledgeEntryModel.id,
            )
        )
        with session_scope(self._session_factory) as session:
            return list(session.scalars(stmt).all())

    def get_by_id(self, entry_id: int) -> FaqKnowledgeEntryModel | None:
        with session_scope(self._session_factory) as session:
            return session.get(FaqKnowledgeEntryModel, entry_id)

    def get_active_by_id(self, entry_id: int) -> FaqKnowledgeEntryModel | None:
        stmt = select(FaqKnowledgeEntryModel).where(
            FaqKnowledgeEntryModel.id == entry_id,
            FaqKnowledgeEntryModel.deleted_at.is_(None),
        )
        with session_scope(self._session_factory) as session:
            return session.scalar(stmt)

    def add_question(
        self,
        *,
        group_entry_id: int,
        question: str,
        embedding: Sequence[float],
        embedding_model: str,
        created_at: datetime,
    ) -> FaqKnowledgeEntryModel | None:
        with session_scope(self._session_factory) as session:
            group_entry = session.scalar(
                select(FaqKnowledgeEntryModel).where(
                    FaqKnowledgeEntryModel.id == group_entry_id,
                    FaqKnowledgeEntryModel.deleted_at.is_(None),
                )
            )
            if group_entry is None:
                return None
            entry = FaqKnowledgeEntryModel(
                question=question,
                answer=group_entry.answer,
                embedding=list(embedding),
                embedding_model=embedding_model,
                created_at=created_at,
            )
            session.add(entry)
            commit(session)
            session.refresh(entry)
            return entry

    def update_group_answer(
        self,
        *,
        group_entry_id: int,
        answer: str,
    ) -> list[FaqKnowledgeEntryModel] | None:
        with session_scope(self._session_factory) as session:
            group_entry = session.scalar(
                select(FaqKnowledgeEntryModel).where(
                    FaqKnowledgeEntryModel.id == group_entry_id,
                    FaqKnowledgeEntryModel.deleted_at.is_(None),
                )
            )
            if group_entry is None:
                return None
            current_answer = group_entry.answer
            entries = list(
                session.scalars(
                    select(FaqKnowledgeEntryModel).where(
                        FaqKnowledgeEntryModel.answer == current_answer,
                        FaqKnowledgeEntryModel.deleted_at.is_(None),
                    )
                ).all()
            )
            for entry in entries:
                entry.answer = answer
            commit(session)
            return list(
                session.scalars(
                    select(FaqKnowledgeEntryModel)
                    .where(
                        FaqKnowledgeEntryModel.answer == answer,
                        FaqKnowledgeEntryModel.deleted_at.is_(None),
                    )
                    .order_by(
                        FaqKnowledgeEntryModel.created_at,
                        FaqKnowledgeEntryModel.id,
                    )
                ).all()
            )

    def soft_delete_entry(self, *, entry_id: int, deleted_at: datetime) -> bool:
        with session_scope(self._session_factory) as session:
            entry = session.scalar(
                select(FaqKnowledgeEntryModel).where(
                    FaqKnowledgeEntryModel.id == entry_id,
                    FaqKnowledgeEntryModel.deleted_at.is_(None),
                )
            )
            if entry is None:
                return False
            entry.deleted_at = deleted_at
            commit(session)
            return True

    def soft_delete_group(
        self,
        *,
        group_entry_id: int,
        deleted_at: datetime,
    ) -> int | None:
        with session_scope(self._session_factory) as session:
            group_entry = session.scalar(
                select(FaqKnowledgeEntryModel).where(
                    FaqKnowledgeEntryModel.id == group_entry_id,
                    FaqKnowledgeEntryModel.deleted_at.is_(None),
                )
            )
            if group_entry is None:
                return None
            entries = list(
                session.scalars(
                    select(FaqKnowledgeEntryModel).where(
                        FaqKnowledgeEntryModel.answer == group_entry.answer,
                        FaqKnowledgeEntryModel.deleted_at.is_(None),
                    )
                ).all()
            )
            for entry in entries:
                entry.deleted_at = deleted_at
            commit(session)
            return len(entries)

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

        with session_scope(self._session_factory) as session:
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
