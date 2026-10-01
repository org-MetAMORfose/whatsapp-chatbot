from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.services.faq_knowledge_service import FaqKnowledgeService
from app.services.openai_service import OpenAIEmbeddingResult


def _entry(entry_id: int, question: str, answer: str) -> FaqKnowledgeEntryModel:
    return FaqKnowledgeEntryModel(
        id=entry_id,
        question=question,
        answer=answer,
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        created_at=datetime(2026, 9, 1, 10, entry_id),
    )


@pytest.mark.asyncio
async def test_create_group_generates_one_embedding_per_question() -> None:
    repository = MagicMock()
    repository.create_group.return_value = [
        _entry(1, "Como funciona?", "Por videochamada."),
        _entry(2, "É online?", "Por videochamada."),
    ]
    openai_service = MagicMock()
    openai_service.generate_embedding = AsyncMock(
        return_value=OpenAIEmbeddingResult(
            embedding=[0.1, 0.2],
            model="embedding-model",
            input_tokens=2,
            latency_ms=1,
            raw_response=object(),
        )
    )
    service = FaqKnowledgeService(repository, openai_service)

    group = await service.create_group(
        answer=" Por videochamada. ",
        questions=[" Como funciona? ", "É online?"],
    )

    assert group.id == 1
    assert [entry.question for entry in group.questions] == [
        "Como funciona?",
        "É online?",
    ]
    assert openai_service.generate_embedding.await_count == 2
    created_entries = repository.create_group.call_args.kwargs["entries"]
    assert [entry.question for entry in created_entries] == [
        "Como funciona?",
        "É online?",
    ]
    assert {entry.answer for entry in created_entries} == {"Por videochamada."}


@pytest.mark.asyncio
async def test_create_group_rejects_duplicate_questions_before_embedding() -> None:
    repository = MagicMock()
    openai_service = MagicMock()
    openai_service.generate_embedding = AsyncMock()
    service = FaqKnowledgeService(repository, openai_service)

    with pytest.raises(ValueError, match="must be unique"):
        await service.create_group(
            answer="Resposta",
            questions=["Mesma pergunta", " Mesma pergunta "],
        )

    openai_service.generate_embedding.assert_not_awaited()
    repository.create_group.assert_not_called()


def test_list_groups_uses_exact_answer_as_group_key() -> None:
    repository = MagicMock()
    repository.list_active.return_value = [
        _entry(1, "Pergunta A", "Resposta"),
        _entry(2, "Pergunta B", "Resposta"),
        _entry(3, "Pergunta C", "resposta"),
    ]
    service = FaqKnowledgeService(repository, MagicMock())

    groups = service.list_groups()

    assert [(group.answer, len(group.questions)) for group in groups] == [
        ("Resposta", 2),
        ("resposta", 1),
    ]
