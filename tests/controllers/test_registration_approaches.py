import pytest
from pydantic import ValidationError

from app.controllers.registration_controller import (
    PatientRegistrationRequest,
    ProfessionalRegistrationRequest,
    ProfessionalUpdateRequest,
)

NEW_APPROACHES = ("Behaviorismo", "Humanismo", "Gestalt", "Fenomenologia", "Avaliação neuropsico")


@pytest.mark.parametrize("selected", NEW_APPROACHES)
def test_patient_and_professional_request_models_accept_new_approaches(selected: str) -> None:
    base = {"name": "Ana", "phone": "5511999999999", "area": "Psicoterapia"}
    patient = PatientRegistrationRequest.model_validate({**base, "psychotherapy_approach": selected.upper()})
    assert patient.psychotherapy_approach == selected
    for model in (ProfessionalRegistrationRequest, ProfessionalUpdateRequest):
        professional = model.model_validate({**base, "email": "ana@example.com", "approaches": [selected.upper(), selected]})
        assert professional.approaches == [selected]


@pytest.mark.parametrize("model", [ProfessionalRegistrationRequest, ProfessionalUpdateRequest])
def test_unknown_approaches_remain_invalid(model: type[ProfessionalRegistrationRequest] | type[ProfessionalUpdateRequest]) -> None:
    with pytest.raises(ValidationError):
        model(name="Ana", phone="5511999999999", area="Psicoterapia", email="ana@example.com", approaches=["Inventada"])
