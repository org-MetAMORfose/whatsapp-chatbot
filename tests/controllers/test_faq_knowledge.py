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
