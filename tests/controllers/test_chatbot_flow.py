from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config.settings as config
from app.controllers.chatbot_flow_controller import ChatbotFlowController
from app.domain.enum.chatbot_flow import ChangeEntityType, ChangeOperation
from app.services.chatbot_flow_admin_service import (
    FlowCachePublishError,
    InvalidFlowDraftError,
    ProtectedFlowNodeError,
)
from app.services.chatbot_flow_validation_service import (
    FlowValidationError,
    FlowValidationResult,
)


def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, MagicMock]:
    monkeypatch.setattr(config, "CHATBOT_API_KEY", "secret")
    service = MagicMock()
    service.publish = AsyncMock()
    app = FastAPI()
    app.include_router(ChatbotFlowController(service).router)
    return TestClient(app), service


def headers() -> dict[str, str]:
    return {"X-Chatbot-Api-Key": "secret"}


def test_flow_endpoints_require_authentication(monkeypatch) -> None:
    api, service = client(monkeypatch)

    response = api.post("/chatbot-flow/revisions", json={})

    assert response.status_code == 401
    service.create_draft.assert_not_called()


def test_saves_typed_draft_changes(monkeypatch) -> None:
    api, service = client(monkeypatch)
    service.save_changes.return_value = {"revision_id": 2, "change_count": 1}

    response = api.put(
        "/chatbot-flow/revisions/2/changes",
        headers=headers(),
        json={
            "changes": [
                {
                    "entity_type": "NODE",
                    "operation": "UPDATE",
                    "entity_id": 10,
                    "new_value": {"message": "Nova mensagem"},
                }
            ]
        },
    )

    assert response.status_code == 200
    change = service.save_changes.call_args.args[1][0]
    assert change.entity_type == ChangeEntityType.NODE
    assert change.operation == ChangeOperation.UPDATE
    assert change.entity_id == 10
    assert change.new_value == {"message": "Nova mensagem"}


def test_validation_returns_node_that_contains_error(monkeypatch) -> None:
    api, service = client(monkeypatch)
    service.validate.return_value = FlowValidationResult(
        valid=False,
        errors=[
            FlowValidationError(
                code="NODE_CANNOT_REACH_END",
                message="O nó não possui caminho até um END.",
                node_id=10,
                node_key="sem_saida",
            )
        ],
    )

    response = api.post(
        "/chatbot-flow/revisions/2/validate",
        headers=headers(),
    )

    assert response.status_code == 200
    assert response.json()["errors"][0]["node_id"] == 10
    assert response.json()["errors"][0]["node_key"] == "sem_saida"


def test_required_action_node_delete_returns_structured_error(monkeypatch) -> None:
    api, service = client(monkeypatch)
    service.save_changes.side_effect = ProtectedFlowNodeError(10, "protegido")

    response = api.put(
        "/chatbot-flow/revisions/2/changes",
        headers=headers(),
        json={
            "changes": [
                {
                    "entity_type": "NODE",
                    "operation": "DELETE",
                    "entity_id": 10,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "REQUIRED_ACTION_NODE_DELETE",
        "message": "Um nó com action obrigatória não pode ser apagado.",
        "node_id": 10,
        "node_key": "protegido",
    }


def test_publish_rejects_invalid_graph_with_validation_errors(monkeypatch) -> None:
    api, service = client(monkeypatch)
    validation = FlowValidationResult(
        valid=False,
        errors=[
            FlowValidationError(
                code="END_HAS_TRANSITIONS",
                message="Um nó END não pode possuir transições.",
                node_id=12,
                node_key="fim",
            )
        ],
    )
    service.publish.side_effect = InvalidFlowDraftError(validation)

    response = api.post(
        "/chatbot-flow/revisions/2/publish",
        headers=headers(),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_FLOW"
    assert response.json()["detail"]["errors"][0]["node_key"] == "fim"


def test_publish_reports_retryable_cache_failure(monkeypatch) -> None:
    api, service = client(monkeypatch)
    service.publish.side_effect = FlowCachePublishError(2, 3)

    response = api.post(
        "/chatbot-flow/revisions/2/publish",
        headers=headers(),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "FLOW_CACHE_PUBLISH_FAILED",
        "message": ("O fluxo foi publicado no PostgreSQL, mas a atualização do cache falhou. Repita a publicação desta revisão."),
        "revision_id": 2,
        "version": 3,
        "retryable": True,
    }
