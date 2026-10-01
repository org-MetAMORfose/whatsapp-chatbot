from datetime import datetime
from unittest.mock import MagicMock

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.repository.sql.faq_knowledge_repository import (
    FaqKnowledgeEntryCreate,
    FaqKnowledgeRepository,
)


def test_create_and_get_by_id(session_factory) -> None:
    repository = FaqKnowledgeRepository(session_factory)

    created = repository.create(
        question="Como funciona?",
        answer="Funciona assim.",
        embedding=[0.1, 0.2, 0.3],
        embedding_model="test-model",
        created_at=datetime(2026, 8, 12, 12, 0),
    )
    found = repository.get_by_id(created.id)

    assert found is not None
    assert found.question == "Como funciona?"
    assert found.answer == "Funciona assim."
    assert found.embedding_model == "test-model"


def test_find_similar_maps_cosine_distance_to_similarity() -> None:
    entry = FaqKnowledgeEntryModel(
        id=3,
        question="Pergunta",
        answer="Resposta",
        embedding=[0.1, 0.2],
        embedding_model="test-model",
        created_at=datetime(2026, 8, 12, 12, 0),
    )
    managed_session = MagicMock()
    managed_session.execute.return_value.all.return_value = [(entry, 0.08)]
    context_manager = MagicMock()
    context_manager.__enter__.return_value = managed_session
    session_factory = MagicMock(return_value=context_manager)
    repository = FaqKnowledgeRepository(session_factory)

    candidates = repository.find_similar(
        embedding=[0.3, 0.4],
        embedding_model="test-model",
        limit=5,
    )

    assert len(candidates) == 1
    assert candidates[0].entry_id == 3
    assert candidates[0].similarity_score == 0.92
    managed_session.execute.assert_called_once()


def test_manage_active_faq_group_with_soft_deletes(session_factory) -> None:
    repository = FaqKnowledgeRepository(session_factory)
    created = repository.create_group(
        entries=[
            FaqKnowledgeEntryCreate(
                question="Como funciona?",
                answer="Por videochamada.",
                embedding=[0.1, 0.2, 0.3],
                embedding_model="test-model",
            ),
            FaqKnowledgeEntryCreate(
                question="É online?",
                answer="Por videochamada.",
                embedding=[0.4, 0.5, 0.6],
                embedding_model="test-model",
            ),
        ],
        created_at=datetime(2026, 9, 1, 10, 0),
    )

    assert [entry.id for entry in repository.list_active()] == [
        created[0].id,
        created[1].id,
    ]

    updated = repository.update_group_answer(
        group_entry_id=created[0].id,
        answer="O atendimento é por videochamada.",
    )
    assert updated is not None
    assert {entry.answer for entry in updated} == {
        "O atendimento é por videochamada."
    }

    assert repository.soft_delete_entry(
        entry_id=created[0].id,
        deleted_at=datetime(2026, 9, 2, 10, 0),
    )
    assert [entry.id for entry in repository.list_active()] == [created[1].id]
    persisted = repository.get_by_id(created[0].id)
    assert persisted is not None
    assert persisted.deleted_at == datetime(2026, 9, 2, 10, 0)

    deleted_count = repository.soft_delete_group(
        group_entry_id=created[1].id,
        deleted_at=datetime(2026, 9, 3, 10, 0),
    )
    assert deleted_count == 1
    assert repository.list_active() == []
