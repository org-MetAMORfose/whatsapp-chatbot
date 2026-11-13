from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config.settings as settings
from app.controllers.immediate_care_controller import ImmediateCareController
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel

HEADERS = {"X-Chatbot-Api-Key": "chave"}
NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHATBOT_API_KEY", "chave")


def _client(professionals: MagicMock, requests: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(ImmediateCareController(professionals, requests).router)
    return TestClient(app)


def test_patch_availability_requires_api_key() -> None:
    professionals, requests = MagicMock(), MagicMock()
    client = _client(professionals, requests)
    assert client.patch("/immediate/professionals/3/availability", json={"available": True}).status_code == 401
    assert client.patch("/immediate/professionals/3/availability", json={"available": True}, headers={"X-Chatbot-Api-Key": "x"}).status_code == 401
    assert client.get("/immediate/requests").status_code == 401
    professionals.set_available_for_immediate.assert_not_called()


def test_patch_availability_updates_flag() -> None:
    professionals, requests = MagicMock(), MagicMock()
    professionals.get_by_id.return_value = ProfessionalModel(id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="CRP")
    professionals.set_available_for_immediate.return_value = ProfessionalModel(
        id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="CRP", available_for_immediate=True
    )
    response = _client(professionals, requests).patch("/immediate/professionals/3/availability", json={"available": True}, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"professional_id": 3, "available_for_immediate": True}
    professionals.set_available_for_immediate.assert_called_once_with(9, True, now=ANY)


def test_patch_availability_unknown_professional_is_404() -> None:
    professionals, requests = MagicMock(), MagicMock()
    professionals.get_by_id.return_value = None
    response = _client(professionals, requests).patch("/immediate/professionals/99/availability", json={"available": False}, headers=HEADERS)
    assert response.status_code == 404


def test_get_requests_lists_recent() -> None:
    professionals, requests = MagicMock(), MagicMock()
    request = ImmediateRequestModel(
        id=42,
        patient_person_id=7,
        professional_person_id=9,
        duration_minutes=30,
        amount_cents=6000,
        status="accepted",
        pix_txid="a" * 32,
        pix_refund_id=None,
        room_url="https://exemplo.daily.co/sala",
        paid_at=NOW,
        accepted_at=NOW,
        refunded_at=None,
        expires_at=NOW,
        created_at=NOW,
    )
    request.patient = PersonModel(id=7, phone_number="5511999999999", name="Maria")
    request.professional = PersonModel(id=9, phone_number="5511977776666", name="Dra. Ana")
    requests.list_recent.return_value = [request]
    response = _client(professionals, requests).get("/immediate/requests?limit=5", headers=HEADERS)
    assert response.status_code == 200
    requests.list_recent.assert_called_once_with(limit=5)
    assert response.json() == [
        {
            "id": 42,
            "status": "accepted",
            "duration_minutes": 30,
            "amount_cents": 6000,
            "patient_name": "Maria",
            "patient_phone": "5511999999999",
            "professional_name": "Dra. Ana",
            "professional_phone": "5511977776666",
            "pix_txid": "a" * 32,
            "pix_refund_id": None,
            "room_url": "https://exemplo.daily.co/sala",
            "paid_at": "2026-11-12T20:00:00Z",
            "accepted_at": "2026-11-12T20:00:00Z",
            "refunded_at": None,
            "expires_at": "2026-11-12T20:00:00Z",
            "created_at": "2026-11-12T20:00:00Z",
        }
    ]


def test_get_requests_rejects_bad_limit() -> None:
    client = _client(MagicMock(), MagicMock())
    assert client.get("/immediate/requests?limit=0", headers=HEADERS).status_code == 422
    assert client.get("/immediate/requests?limit=1001", headers=HEADERS).status_code == 422


def test_patch_availability_rejects_ineligible_with_409() -> None:
    professionals, requests = MagicMock(), MagicMock()
    professionals.get_by_id.return_value = ProfessionalModel(
        id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="PENDING_REVIEW"
    )
    response = _client(professionals, requests).patch("/immediate/professionals/3/availability", json={"available": True}, headers=HEADERS)
    assert response.status_code == 409
    professionals.set_available_for_immediate.assert_not_called()
    professionals.set_available_for_immediate.return_value = ProfessionalModel(
        id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="PENDING_REVIEW", available_for_immediate=False
    )
    off = _client(professionals, requests).patch("/immediate/professionals/3/availability", json={"available": False}, headers=HEADERS)
    assert off.status_code == 200 and off.json()["available_for_immediate"] is False
