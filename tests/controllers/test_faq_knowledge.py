from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config.settings as config
from app.controllers.faq_knowledge_controller import FaqKnowledgeController
from app.domain.db.faq_knowledge_entry_model import FaqKnowledgeEntryModel
from app.services.openai_service import OpenAIEmbeddingResult


def _client(monkeypatch, *, configured_key: str = "secret"):
    monkeypatch.setattr(config, "CHATBOT_API_KEY", configured_key)
    repository = MagicMock()
    repository.create.return_value = FaqKnowledgeEntryModel(
        id=42,
        question="Como funciona?",
        answer="Funciona assim.",
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        created_at=datetime(2026, 8, 12, 12, 0),
    )
    openai_service = MagicMock()
    openai_service.generate_embedding = AsyncMock(
        return_value=OpenAIEmbeddingResult(
            embedding=[0.1, 0.2],
            model="embedding-model",
            input_tokens=4,
            latency_ms=10,
            raw_response=object(),
        )
    )
    controller = FaqKnowledgeController(repository, openai_service)
    app = FastAPI()
    app.include_router(controller.router)
    return TestClient(app), repository, openai_service


def test_create_entry_requires_chatbot_api_key(monkeypatch) -> None:
    client, repository, openai_service = _client(monkeypatch)

    response = client.post(
        "/faq/knowledge-entries",
        json={"question": "Como funciona?", "answer": "Funciona assim."},
    )

    assert response.status_code == 401
    repository.create.assert_not_called()
    openai_service.generate_embedding.assert_not_awaited()


def test_create_entry_returns_201_and_persists_embedding(monkeypatch) -> None:
    client, repository, openai_service = _client(monkeypatch)

    response = client.post(
        "/faq/knowledge-entries",
        headers={"X-Chatbot-Api-Key": "secret"},
        json={"question": " Como funciona? ", "answer": " Funciona assim. "},
    )

    assert response.status_code == 201
    assert response.json() == {
        "id": 42,
        "embedding_model": "embedding-model",
        "created_at": "2026-08-12T12:00:00",
    }
    openai_service.generate_embedding.assert_awaited_once_with("Como funciona?")
    repository.create.assert_called_once()
    created = repository.create.call_args.kwargs
    assert created["question"] == "Como funciona?"
    assert created["answer"] == "Funciona assim."
    assert created["embedding"] == [0.1, 0.2]


def test_create_entry_rejects_blank_values(monkeypatch) -> None:
    client, repository, _ = _client(monkeypatch)

    response = client.post(
        "/faq/knowledge-entries",
        headers={"X-Chatbot-Api-Key": "secret"},
        json={"question": "   ", "answer": "Resposta"},
    )

    assert response.status_code == 422
    repository.create.assert_not_called()


def test_create_entry_reports_missing_server_authentication(monkeypatch) -> None:
    client, _, _ = _client(monkeypatch, configured_key="")

    response = client.post(
        "/faq/knowledge-entries",
        headers={"X-Chatbot-Api-Key": "anything"},
        json={"question": "Pergunta", "answer": "Resposta"},
    )

    assert response.status_code == 503


def test_list_groups_groups_questions_by_exact_answer(monkeypatch) -> None:
    client, repository, _ = _client(monkeypatch)
    repository.list_active.return_value = [
        FaqKnowledgeEntryModel(
            id=1,
            question="Como funciona?",
            answer="Por videochamada.",
            embedding=[0.1, 0.2],
            embedding_model="embedding-model",
            created_at=datetime(2026, 8, 12, 12, 0),
        ),
        FaqKnowledgeEntryModel(
            id=2,
            question="É online?",
            answer="Por videochamada.",
            embedding=[0.1, 0.2],
            embedding_model="embedding-model",
            created_at=datetime(2026, 8, 12, 12, 1),
        ),
    ]

    response = client.get(
        "/faq/knowledge-groups",
        headers={"X-Chatbot-Api-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "groups": [
            {
                "id": 1,
                "answer": "Por videochamada.",
                "questions": [
                    {
                        "id": 1,
                        "question": "Como funciona?",
                        "created_at": "2026-08-12T12:00:00",
                    },
                    {
                        "id": 2,
                        "question": "É online?",
                        "created_at": "2026-08-12T12:01:00",
                    },
                ],
            }
        ]
    }


def test_update_and_soft_delete_group(monkeypatch) -> None:
    client, repository, openai_service = _client(monkeypatch)
    updated = FaqKnowledgeEntryModel(
        id=5,
        question="Pergunta",
        answer="Resposta atualizada",
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        created_at=datetime(2026, 8, 12, 12, 0),
    )
    repository.update_group_answer.return_value = [updated]
    repository.soft_delete_group.return_value = 3

    update_response = client.patch(
        "/faq/knowledge-groups/5",
        headers={"X-Chatbot-Api-Key": "secret"},
        json={"answer": " Resposta atualizada "},
    )
    delete_response = client.delete(
        "/faq/knowledge-groups/5",
        headers={"X-Chatbot-Api-Key": "secret"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["answer"] == "Resposta atualizada"
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted_count": 3}
    repository.update_group_answer.assert_called_once_with(
        group_entry_id=5,
        answer="Resposta atualizada",
    )
    openai_service.generate_embedding.assert_not_awaited()


def test_delete_question_uses_soft_delete(monkeypatch) -> None:
    client, repository, _ = _client(monkeypatch)
    repository.soft_delete_entry.return_value = True

    response = client.delete(
        "/faq/knowledge-entries/7",
        headers={"X-Chatbot-Api-Key": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"id": 7, "deleted": True}
    assert repository.soft_delete_entry.call_args.kwargs["entry_id"] == 7
    assert repository.soft_delete_entry.call_args.kwargs["deleted_at"] is not None


def test_create_group_generates_embeddings_for_all_questions(monkeypatch) -> None:
    client, repository, openai_service = _client(monkeypatch)
    repository.create_group.return_value = [
        FaqKnowledgeEntryModel(
            id=8,
            question="Pergunta A",
            answer="Resposta comum",
            embedding=[0.1, 0.2],
            embedding_model="embedding-model",
            created_at=datetime(2026, 8, 12, 12, 0),
        ),
        FaqKnowledgeEntryModel(
            id=9,
            question="Pergunta B",
            answer="Resposta comum",
            embedding=[0.1, 0.2],
            embedding_model="embedding-model",
            created_at=datetime(2026, 8, 12, 12, 1),
        ),
    ]

    response = client.post(
        "/faq/knowledge-groups",
        headers={"X-Chatbot-Api-Key": "secret"},
        json={
            "answer": "Resposta comum",
            "questions": ["Pergunta A", "Pergunta B"],
        },
    )

    assert response.status_code == 201
    assert len(response.json()["questions"]) == 2
    assert openai_service.generate_embedding.await_count == 2
    repository.create_group.assert_called_once()


def test_add_question_to_existing_group(monkeypatch) -> None:
    client, repository, openai_service = _client(monkeypatch)
    existing = FaqKnowledgeEntryModel(
        id=10,
        question="Pergunta original",
        answer="Resposta",
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        created_at=datetime(2026, 8, 12, 12, 0),
    )
    created = FaqKnowledgeEntryModel(
        id=11,
        question="Nova pergunta",
        answer="Resposta",
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        created_at=datetime(2026, 8, 12, 12, 1),
    )
    repository.get_active_by_id.return_value = existing
    repository.add_question.return_value = created
    repository.list_active.return_value = [existing, created]

    response = client.post(
        "/faq/knowledge-groups/10/questions",
        headers={"X-Chatbot-Api-Key": "secret"},
        json={"question": " Nova pergunta "},
    )

    assert response.status_code == 201
    assert [item["question"] for item in response.json()["questions"]] == [
        "Pergunta original",
        "Nova pergunta",
    ]
    openai_service.generate_embedding.assert_awaited_once_with("Nova pergunta")
    assert repository.add_question.call_args.kwargs["group_entry_id"] == 10
