from datetime import datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.faq_session_model import FaqSessionModel
from app.domain.enum.faq_answer_status import FaqAnswerStatus
from app.domain.enum.faq_session_outcome import FaqSessionOutcome
from app.repository.sql.faq_session_repository import FaqSessionRepository


@pytest.fixture
def faq_session_repository(
    session_factory: sessionmaker[Session],
) -> FaqSessionRepository:
    return FaqSessionRepository(session_factory)


def test_get_or_create_active_creates_first_session(
    faq_session_repository: FaqSessionRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11950000001")
    now = datetime(2026, 8, 12, 12, 0)

    faq_session = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=now,
    )

    assert faq_session.id is not None
    assert faq_session.outcome == FaqSessionOutcome.ACTIVE
    assert faq_session.created_at == now


def test_get_or_create_active_reuses_recent_session(
    faq_session_repository: FaqSessionRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11950000002")
    first = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 0),
    )

    reused = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 59),
    )

    assert reused.id == first.id


def test_get_or_create_active_abandons_session_after_one_hour(
    faq_session_repository: FaqSessionRepository,
    session_factory: sessionmaker[Session],
    make_person,
) -> None:
    person = make_person(phone_number="11950000003")
    first = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 0),
    )

    replacement = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 13, 0),
    )

    with session_factory() as session:
        abandoned = session.get(FaqSessionModel, first.id)

    assert replacement.id != first.id
    assert replacement.outcome == FaqSessionOutcome.ACTIVE
    assert abandoned is not None
    assert abandoned.outcome == FaqSessionOutcome.ABANDONED


def test_last_question_extends_active_session(
    faq_session_repository: FaqSessionRepository,
    make_message_history,
    make_person,
) -> None:
    person = make_person(phone_number="11950000004")
    first = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 10, 0),
    )
    question = make_message_history(person_id=person.id, content="Dúvida")
    faq_session_repository.record_interaction(
        session_id=first.id,
        question_message_id=question.id,
        selected_entry_id=None,
        answer_status=FaqAnswerStatus.NOT_FOUND,
        similarity_score=None,
        latency_ms=10,
        input_tokens=5,
        output_tokens=0,
        created_at=datetime(2026, 8, 12, 11, 30),
    )

    reused = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 29),
    )

    assert reused.id == first.id


def test_terminal_latest_session_causes_a_new_active_session(
    faq_session_repository: FaqSessionRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11950000005")
    first = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 0),
    )
    faq_session_repository.update_outcome(
        first.id,
        FaqSessionOutcome.ESCALATED,
    )

    replacement = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 5),
    )

    assert replacement.id != first.id
    assert replacement.outcome == FaqSessionOutcome.ACTIVE


def test_record_interaction_increments_question_count(
    faq_session_repository: FaqSessionRepository,
    session_factory: sessionmaker[Session],
    make_message_history,
    make_person,
) -> None:
    person = make_person(phone_number="11950000006")
    faq_session = faq_session_repository.get_or_create_active(
        person_id=person.id,
        now=datetime(2026, 8, 12, 12, 0),
    )
    first_message = make_message_history(person_id=person.id, content="Primeira")
    second_message = make_message_history(person_id=person.id, content="Segunda")

    first = faq_session_repository.record_interaction(
        session_id=faq_session.id,
        question_message_id=first_message.id,
        selected_entry_id=None,
        answer_status=FaqAnswerStatus.NOT_FOUND,
        similarity_score=None,
        latency_ms=10,
        input_tokens=5,
        output_tokens=0,
        created_at=datetime(2026, 8, 12, 12, 1),
    )
    second = faq_session_repository.record_interaction(
        session_id=faq_session.id,
        question_message_id=second_message.id,
        selected_entry_id=None,
        answer_status=FaqAnswerStatus.NOT_FOUND,
        similarity_score=None,
        latency_ms=12,
        input_tokens=6,
        output_tokens=0,
        created_at=datetime(2026, 8, 12, 12, 2),
    )

    with session_factory() as session:
        persisted_session = session.get(FaqSessionModel, faq_session.id)

    assert first.question_number == 1
    assert second.question_number == 2
    assert persisted_session is not None
    assert persisted_session.question_count == 2
