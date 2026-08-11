from datetime import datetime

from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.faq_interaction_model import FaqInteractionModel
from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.domain.db.faq_session_model import FaqSessionModel
from app.domain.enum.faq_answer_status import FaqAnswerStatus
from app.domain.enum.faq_session_outcome import FaqSessionOutcome


def test_faq_schema_columns_and_nullability() -> None:
    session_columns = inspect(FaqSessionModel).columns
    knowledge_columns = inspect(FaqKnowledgeEntryModel).columns
    interaction_columns = inspect(FaqInteractionModel).columns

    assert set(session_columns.keys()) == {
        "id",
        "person_id",
        "outcome",
        "question_count",
        "created_at",
    }
    assert knowledge_columns.embedding.nullable is False
    assert knowledge_columns.deleted_at.nullable is True
    assert interaction_columns.question_message_id.nullable is False
    assert interaction_columns.selected_entry_id.nullable is True
    assert interaction_columns.answer_status.nullable is True


def test_faq_models_persist_session_knowledge_and_interaction(
    session_factory: sessionmaker[Session],
    make_person,
    make_message_history,
) -> None:
    now = datetime.utcnow()
    person = make_person(phone_number="11940000001")
    question_message = make_message_history(
        person_id=person.id,
        content="Como funciona o atendimento?",
    )

    with session_factory() as session:
        faq_session = FaqSessionModel(person_id=person.id, created_at=now)
        knowledge_entry = FaqKnowledgeEntryModel(
            question="Como funciona o atendimento?",
            answer="O atendimento é realizado por videochamada.",
            embedding=[0.1, 0.2, 0.3],
            embedding_model="test-embedding-model",
            created_at=now,
        )
        session.add_all([faq_session, knowledge_entry])
        session.flush()

        interaction = FaqInteractionModel(
            session_id=faq_session.id,
            question_message_id=question_message.id,
            selected_entry_id=knowledge_entry.id,
            question_number=1,
            answer_status=FaqAnswerStatus.SATISFIED,
            similarity_score=0.92,
            latency_ms=350,
            input_tokens=120,
            output_tokens=45,
            created_at=now,
        )
        session.add(interaction)
        session.commit()
        session.refresh(faq_session)
        session.refresh(interaction)

        assert faq_session.outcome == FaqSessionOutcome.ACTIVE
        assert faq_session.question_count == 0
        assert faq_session.interactions == [interaction]
        assert interaction.question_message.id == question_message.id
        assert interaction.selected_entry is not None
        assert interaction.selected_entry.id == knowledge_entry.id
