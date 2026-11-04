import pytest

from app.domain.matching import PatientRegistration
from app.domain.matching.profile import (
    APPROACHES,
    append_specialty_answer,
    approach,
    patient_request,
    professional_profile,
)
from matching.input import validate_patient


@pytest.mark.parametrize("selected", APPROACHES)
def test_all_flow_approaches_survive_registration_normalization(selected: str) -> None:
    raw = f"  {selected.upper()}  "
    assert approach(raw) == selected
    assert professional_profile(areas=["Psicoterapia"], approaches=[raw])["psychotherapy"]["approaches"] == [selected]
    registration = validate_patient({
        "name": "Ana", "area": "Psicoterapia", "phone_number": "5511999999999",
        "birth_date": "2000-01-01", "psychotherapy_approach": raw,
    })
    assert isinstance(registration, PatientRegistration)
    assert registration.matching_request is not None
    assert registration.matching_request["psychotherapy"]["approach"] == selected


@pytest.mark.parametrize("gender", ["Homem", "Mulher", "Não binário"])
def test_legacy_gender_choices_are_preserved(gender: str) -> None:
    assert patient_request(selected_area="Psicoterapia", professional_profile=gender)["professional_preferences"]["gender"] == gender


@pytest.mark.parametrize(("answer", "canonical"), [
    ("Negro", "Negra"), ("Branco", "Branca"), ("Indígena", "Indígena"),
    ("Asiático", "Asiática"), ("Imigrante", "Imigrante"),
])
def test_legacy_self_declarations_populate_matching_profile(answer: str, canonical: str) -> None:
    assert professional_profile(areas=["Psicoterapia"], minority_group=answer)["profile"]["race"] == canonical


def test_explicit_gender_and_declaration_override_legacy_preferences() -> None:
    request = patient_request(selected_area="Psicoterapia", professional_profile="Mulher negra",
                              preferred_gender="Homem", preferred_race="Branco")
    assert request["professional_preferences"] == {"gender": "Homem", "race": "Branca", "lgbtqiapn_plus": None}
    request = patient_request(selected_area="Psicoterapia", professional_profile="Mulher negra",
                              preferred_gender="Sem preferência", preferred_race="Sem preferência")
    assert request["professional_preferences"] == {"gender": None, "race": None, "lgbtqiapn_plus": None}


def test_specialty_answers_accumulate_and_skip_without_erasing_previous_choices() -> None:
    choices = append_specialty_answer(None, "LGBTQIAPN+")
    choices = append_specialty_answer(choices, "Boderline, Ansiedade, borderline")
    choices = append_specialty_answer(choices, "Sem preferência")
    choices = append_specialty_answer(choices, "Sem preferêcnia")
    choices = append_specialty_answer(choices, "  ansiedade  , Burnout")
    assert choices == ["LGBTQIAPN+", "Transtorno de Personalidade Borderline", "Ansiedade", "Burnout"]
    assert append_specialty_answer(None, "Sem preferência") == []


def test_non_psychotherapy_requests_do_not_keep_psychotherapy_fields() -> None:
    request = patient_request(selected_area="Nutrição", selected_approach="Gestalt", focus=["Autismo"])
    assert request["psychotherapy"] == {"approach": None, "specialties": []}
