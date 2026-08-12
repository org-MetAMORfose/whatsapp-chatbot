"""SQL repository for FAQ sessions and interactions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.db.faq_interaction_model import FaqInteractionModel
from app.domain.db.faq_session_model import FaqSessionModel
from app.domain.enum.faq_answer_status import FaqAnswerStatus
from app.domain.enum.faq_session_outcome import FaqSessionOutcome

FAQ_SESSION_INACTIVITY_TIMEOUT = timedelta(hours=1)


class FaqSessionRepository:
    """Manage FAQ session lifecycle and interaction analytics."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def get_or_create_active(
        self,
        *,
        person_id: int,
        now: datetime,
    ) -> FaqSessionModel:
        """Reuse the latest active session or abandon it after one idle hour."""
        with self._session_factory() as session:
            latest = session.scalar(
                select(FaqSessionModel)
                .where(FaqSessionModel.person_id == person_id)
                .order_by(FaqSessionModel.created_at.desc(), FaqSessionModel.id.desc())
                .limit(1)
                .with_for_update()
            )

            if latest is not None and latest.outcome == FaqSessionOutcome.ACTIVE:
                if not self._is_abandoned(session, latest, now):
                    return latest
                latest.outcome = FaqSessionOutcome.ABANDONED

            faq_session = FaqSessionModel(
                person_id=person_id,
                outcome=FaqSessionOutcome.ACTIVE,
                created_at=now,
            )
            session.add(faq_session)
            session.commit()
            session.refresh(faq_session)
            return faq_session

    def record_interaction(
        self,
        *,
        session_id: int,
        question_message_id: int,
        selected_entry_id: int | None,
        answer_status: FaqAnswerStatus | None,
        similarity_score: float | None,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        created_at: datetime,
    ) -> FaqInteractionModel:
        """Increment the question counter and persist its interaction atomically."""
        with self._session_factory() as session:
            faq_session = session.scalar(
                select(FaqSessionModel)
                .where(FaqSessionModel.id == session_id)
                .with_for_update()
            )
            if faq_session is None:
                raise ValueError(f"FAQ session {session_id} was not found.")

            faq_session.question_count += 1
            interaction = FaqInteractionModel(
                session_id=faq_session.id,
                question_message_id=question_message_id,
                selected_entry_id=selected_entry_id,
                question_number=faq_session.question_count,
                answer_status=answer_status,
                similarity_score=similarity_score,
                latency_ms=latency_ms,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                created_at=created_at,
            )
            session.add(interaction)
            session.commit()
            session.refresh(interaction)
            return interaction

    def update_outcome(
        self,
        session_id: int,
        outcome: FaqSessionOutcome,
    ) -> FaqSessionModel:
        with self._session_factory() as session:
            faq_session = session.get(FaqSessionModel, session_id)
            if faq_session is None:
                raise ValueError(f"FAQ session {session_id} was not found.")
            faq_session.outcome = outcome
            session.commit()
            session.refresh(faq_session)
            return faq_session

    def finish_latest_active(
        self,
        *,
        person_id: int,
        outcome: FaqSessionOutcome,
        answer_status: FaqAnswerStatus | None = None,
    ) -> FaqSessionModel | None:
        """Finish the person's latest active FAQ session atomically."""
        with self._session_factory() as session:
            faq_session = session.scalar(
                select(FaqSessionModel)
                .where(
                    FaqSessionModel.person_id == person_id,
                    FaqSessionModel.outcome == FaqSessionOutcome.ACTIVE,
                )
                .order_by(FaqSessionModel.created_at.desc(), FaqSessionModel.id.desc())
                .limit(1)
                .with_for_update()
            )
            if faq_session is None:
                return None

            if answer_status is not None:
                interaction = session.scalar(
                    select(FaqInteractionModel)
                    .where(FaqInteractionModel.session_id == faq_session.id)
                    .order_by(
                        FaqInteractionModel.question_number.desc(),
                        FaqInteractionModel.id.desc(),
                    )
                    .limit(1)
                    .with_for_update()
                )
                if interaction is not None:
                    interaction.answer_status = answer_status

            faq_session.outcome = outcome
            session.commit()
            session.refresh(faq_session)
            return faq_session

    @staticmethod
    def _is_abandoned(
        session: Session,
        faq_session: FaqSessionModel,
        now: datetime,
    ) -> bool:
        last_question_at = session.scalar(
            select(func.max(FaqInteractionModel.created_at)).where(
                FaqInteractionModel.session_id == faq_session.id
            )
        )
        last_activity_at = last_question_at or faq_session.created_at
        return now - last_activity_at >= FAQ_SESSION_INACTIVITY_TIMEOUT
