from datetime import date
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.registration_controller import RegistrationController
from app.services.registration_service import RegisteredPatient, RegisteredProfessional


def _client(service: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(RegistrationController(service).router)
    return TestClient(app)


def test_register_single_patient_accepts_sheet_fields() -> None:
    service = MagicMock()
    service.register_patients.return_value = [RegisteredPatient(id=10, person_id=20)]
    client = _client(service)

    response = client.post(
        "/patients",
        json={
            "name": " Ana ",
            "phone": "https://wa.me/5511999999999",
            "area": " Psicoterapia ",
            "birth_date": "31/01/1990",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "patients": [{"id": 10, "person_id": 20, "matching_status": "requested"}]
    }
    registration = service.register_patients.call_args.args[0][0]
    assert registration.name == "Ana"
    assert registration.phone == "5511999999999"
    assert registration.area == "Psicoterapia"
    assert registration.birth_date == date(1990, 1, 31)


def test_register_patient_list() -> None:
    service = MagicMock()
    service.register_patients.return_value = [
        RegisteredPatient(id=1, person_id=11),
        RegisteredPatient(id=2, person_id=22),
    ]
    client = _client(service)

    response = client.post(
        "/patients",
        json=[
            {"name": "Ana", "phone": "5511999999991", "area": "Psicoterapia"},
            {"name": "Bia", "phone": "5511999999992", "area": "Nutrição"},
        ],
    )

    assert response.status_code == 201
    assert len(response.json()["patients"]) == 2
    assert len(service.register_patients.call_args.args[0]) == 2


def test_register_patients_rejects_empty_list_and_missing_required_fields() -> None:
    service = MagicMock()
    client = _client(service)

    assert client.post("/patients", json=[]).status_code == 422
    assert client.post(
        "/patients",
        json={"name": "Ana", "phone": "5511999999999"},
    ).status_code == 422
    service.register_patients.assert_not_called()


def test_register_professional_with_pending_register_defaults() -> None:
    service = MagicMock()
    service.register_professional.return_value = RegisteredProfessional(id=30, person_id=40)
    client = _client(service)

    response = client.post(
        "/professionals",
        json={
            "name": "Carla",
            "phone": "+55 (11) 98888-7777",
            "email": "carla@example.com",
            "area": "Psicoterapia",
            "approach": " TCC ",
        },
    )

    assert response.status_code == 201
    assert response.json() == {"id": 30, "person_id": 40}
    registration = service.register_professional.call_args.args[0]
    assert registration.phone == "5511988887777"
    assert registration.email == "carla@example.com"
    assert registration.approach == "TCC"
    assert registration.professional_register is None
    assert registration.register_type is None
