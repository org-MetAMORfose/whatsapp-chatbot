from datetime import datetime
from unittest.mock import MagicMock

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository


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
