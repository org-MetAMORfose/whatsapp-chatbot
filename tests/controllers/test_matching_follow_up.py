from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.matching_follow_up_controller import MatchingFollowUpController
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel


def _client(
    people: MagicMock,
    patients: MagicMock,
    professionals: MagicMock,
    whatsapp: MagicMock,
    follow_ups: MagicMock | None = None,
) -> TestClient:
    follow_ups = follow_ups or MagicMock()
    follow_ups.mark = AsyncMock()
    app = FastAPI()
    app.include_router(
        MatchingFollowUpController(
            people,
            patients,
            professionals,
            whatsapp,
            follow_ups,
        ).router
    )
    return TestClient(app)


def test_send_matching_follow_up_uses_database_data_in_template_order() -> None:
    patient_person = PersonModel(id=1, phone_number="5511999991111", name="Ana")
    professional_person = PersonModel(id=2, phone_number="5511988882222", name="Bruno")
    professional = ProfessionalModel(id=3, person_id=2, area="Psicoterapia")
    people = MagicMock()
    people.get_by_phone_number_and_channel.side_effect = [
        patient_person,
        professional_person,
    ]
    patients = MagicMock()
    patients.exists_by_person_id.return_value = True
    professionals = MagicMock()
    professionals.get_by_person_id.return_value = professional
    whatsapp = MagicMock()
    whatsapp.send_template = AsyncMock(return_value="wamid.follow-up")
    follow_ups = MagicMock()
    client = _client(people, patients, professionals, whatsapp, follow_ups)

    response = client.post(
        "/whatsapp/templates/acompanhamento_emparelhamento",
        json={
            "patient_phone": "+55 (11) 99999-1111",
            "professional_phone": "https://wa.me/5511988882222",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "sent", "message_id": "wamid.follow-up"}
    whatsapp.send_template.assert_awaited_once_with(
        to="5511999991111",
        name="acompanhamento_emparelhamento",
        language="pt_BR",
        body_parameters=(
            "Ana",
            "Bruno",
            "Psicoterapia",
            "https://wa.me/5511988882222",
        ),
    )
    history = people.create_message.call_args.args[0]
    assert history.person_id == 1
    assert history.is_from_user is False
    assert history.content == (
        "[template:acompanhamento_emparelhamento:pt_BR] "
        "Ana | Bruno | Psicoterapia | https://wa.me/5511988882222"
    )
    follow_ups.mark.assert_awaited_once_with("5511999991111", Channel.WHATSAPP)


def test_send_matching_follow_up_returns_404_for_unknown_patient() -> None:
    people = MagicMock()
    people.get_by_phone_number_and_channel.return_value = None
    patients = MagicMock()
    professionals = MagicMock()
    whatsapp = MagicMock()
    whatsapp.send_template = AsyncMock()
    client = _client(people, patients, professionals, whatsapp)

    response = client.post(
        "/whatsapp/templates/acompanhamento_emparelhamento",
        json={
            "patient_phone": "5511999991111",
            "professional_phone": "5511988882222",
        },
    )

    assert response.status_code == 404
    whatsapp.send_template.assert_not_awaited()


def test_send_matching_follow_up_maps_whatsapp_error_to_bad_gateway() -> None:
    patient_person = PersonModel(id=1, phone_number="5511999991111", name="Ana")
    professional_person = PersonModel(id=2, phone_number="5511988882222", name="Bruno")
    professional = ProfessionalModel(id=3, person_id=2, area="Psicoterapia")
    people = MagicMock()
    people.get_by_phone_number_and_channel.side_effect = [
        patient_person,
        professional_person,
    ]
    patients = MagicMock()
    patients.exists_by_person_id.return_value = True
    professionals = MagicMock()
    professionals.get_by_person_id.return_value = professional
    whatsapp = MagicMock()
    request = httpx.Request("POST", "https://graph.facebook.com/messages")
    response = httpx.Response(400, request=request)
    whatsapp.send_template = AsyncMock(
        side_effect=httpx.HTTPStatusError("bad request", request=request, response=response)
    )
    client = _client(people, patients, professionals, whatsapp)

    result = client.post(
        "/whatsapp/templates/acompanhamento_emparelhamento",
        json={
            "patient_phone": "5511999991111",
            "professional_phone": "5511988882222",
        },
    )

    assert result.status_code == 502
    people.create_message.assert_not_called()
