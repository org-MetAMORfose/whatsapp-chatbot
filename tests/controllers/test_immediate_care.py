from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config.settings as settings
from app.controllers.immediate_care_controller import ImmediateCareController
from app.domain.db.professional_model import ProfessionalModel

HEADERS = {"X-Chatbot-Api-Key": "chave"}
NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHATBOT_API_KEY", "chave")


def _client(professionals: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(ImmediateCareController(professionals).router)
    return TestClient(app)


def psychologist(**extra: object) -> ProfessionalModel:
    professional = ProfessionalModel(id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="CRP")
    professional.available_for_immediate = False
    professional.immediate_approved_at = None
    for key, value in extra.items():
        setattr(professional, key, value)
    return professional


def test_endpoints_require_the_api_key() -> None:
    professionals = MagicMock()
    client = _client(professionals)
    for path, body in (("availability", {"available": True}), ("approval", {"approved": True})):
        assert client.patch(f"/immediate/professionals/3/{path}", json=body).status_code == 401
        assert client.patch(f"/immediate/professionals/3/{path}", json=body, headers={"X-Chatbot-Api-Key": "x"}).status_code == 401
    professionals.set_available_for_immediate.assert_not_called()
    professionals.set_immediate_approval.assert_not_called()


def test_no_endpoint_lists_patient_requests() -> None:
    """The panel reads requests from the database; the API on port 8000 never returns patient phones or room links."""
    assert _client(MagicMock()).get("/immediate/requests", headers=HEADERS).status_code == 404


def test_approval_releases_a_psychologist() -> None:
    professionals = MagicMock()
    professionals.get_by_id.return_value = psychologist()
    professionals.set_immediate_approval.return_value = psychologist(immediate_approved_at=NOW)
    response = _client(professionals).patch("/immediate/professionals/3/approval", json={"approved": True}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"professional_id": 3, "immediate_approved_at": "2026-11-12T20:00:00Z", "available_for_immediate": False}
    professionals.set_immediate_approval.assert_called_once_with(3, True, now=ANY)


def test_approval_is_open_to_every_area() -> None:
    professionals = MagicMock()
    professionals.get_by_id.return_value = psychologist(area="Nutrição")
    professionals.set_immediate_approval.return_value = psychologist(area="Nutrição", immediate_approved_at=NOW)
    response = _client(professionals).patch("/immediate/professionals/3/approval", json={"approved": True}, headers=HEADERS)
    assert response.status_code == 200
    professionals.set_immediate_approval.assert_called_once()


def test_approval_can_be_withdrawn_from_anyone() -> None:
    professionals = MagicMock()
    professionals.get_by_id.return_value = psychologist(area="Nutrição", immediate_approved_at=NOW)
    professionals.set_immediate_approval.return_value = psychologist(area="Nutrição")
    response = _client(professionals).patch("/immediate/professionals/3/approval", json={"approved": False}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["immediate_approved_at"] is None
    professionals.set_immediate_approval.assert_called_once_with(3, False, now=ANY)


def test_availability_updates_flag_of_a_released_psychologist() -> None:
    professionals = MagicMock()
    professionals.get_by_id.return_value = psychologist(immediate_approved_at=NOW)
    professionals.set_available_for_immediate.return_value = psychologist(immediate_approved_at=NOW, available_for_immediate=True)
    response = _client(professionals).patch("/immediate/professionals/3/availability", json={"available": True}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"professional_id": 3, "immediate_approved_at": "2026-11-12T20:00:00Z", "available_for_immediate": True}
    professionals.set_available_for_immediate.assert_called_once_with(9, True, now=ANY)


def test_availability_refuses_a_psychologist_the_team_did_not_release() -> None:
    """register_type comes from the public registration body, so it never makes anyone eligible."""
    professionals = MagicMock()
    professionals.get_by_id.return_value = psychologist(register_type="CRP")
    response = _client(professionals).patch("/immediate/professionals/3/availability", json={"available": True}, headers=HEADERS)
    assert response.status_code == 409
    professionals.set_available_for_immediate.assert_not_called()


def test_availability_unknown_professional_is_404() -> None:
    professionals = MagicMock()
    professionals.get_by_id.return_value = None
    response = _client(professionals).patch("/immediate/professionals/99/availability", json={"available": False}, headers=HEADERS)
    assert response.status_code == 404
