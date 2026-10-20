from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain.matching import Candidate, Patient
from app.domain.matching.profile import patient_request, professional_profile
from matching.domain import compatibility, rank, score_candidate, urgency_score

REFERENCE_TIME = datetime(2000, 1, 1, tzinfo=UTC)


def cycle(**changes: Any) -> Candidate:
    base = {
        "id": 1, "area": "Psicoterapia", "approach": "TCC", "gender": "Mulher",
        "minority_group": "Negro LGBT",
        "starts_at": REFERENCE_TIME - timedelta(days=30),
        "deadline_at": REFERENCE_TIME + timedelta(days=20),
        "cancelled_at": None, "promised_patients": 1, "used": 0,
    }
    return Candidate(**{**base, **changes})


def test_optional_preferences_count_matches_without_excluding_candidates():
    patient = Patient(1, "Psicoterapia", "TCC", "Mulher negra")
    assert compatibility(patient, cycle()) == 2
    assert compatibility(patient, cycle(gender="Homem", minority_group=None)) == 0
    assert score_candidate(patient, cycle(gender="Homem", minority_group=None), REFERENCE_TIME) is not None


def test_specific_approach_is_required_and_unspecified_professional_is_generic_only():
    tcc = Patient(1, "Psicoterapia", "TCC")
    generic = Patient(2, "Psicoterapia")
    assert score_candidate(tcc, cycle(approach=None), REFERENCE_TIME) is None
    assert score_candidate(tcc, cycle(approach="Psicanálise"), REFERENCE_TIME) is None
    assert score_candidate(generic, cycle(approach=None), REFERENCE_TIME) is not None
    both = professional_profile(areas=["Psicoterapia"], approaches=["TCC", "Psicanálise"])
    assert score_candidate(tcc, cycle(matching_profile=both), REFERENCE_TIME) is not None
    assert score_candidate(Patient(3, "Psicoterapia", "Psicanálise"),
                           cycle(matching_profile=both), REFERENCE_TIME) is not None


def test_multi_area_professional_and_specialties():
    profile = professional_profile(areas=["Psicoterapia", "Psiquiatria"], approaches=["TCC"],
                                   focus=["Ansiedade"], gender="Mulher", race="Negra", lgbtqiapn_plus=True)
    request = patient_request(selected_area="Psicoterapia", selected_approach="TCC",
                              focus=["Ansiedade"], preferred_gender="Mulher",
                              preferred_race="Negra", prefers_lgbtqiapn_plus=True)
    patient = Patient(1, "Psicoterapia", matching_request=request)
    assert compatibility(patient, cycle(matching_profile=profile)) == 3
    assert score_candidate(Patient(2, "Psiquiatria"),
                           cycle(matching_profile=profile), REFERENCE_TIME) is not None


def test_specialties_prioritize_but_do_not_exclude_professionals():
    request = patient_request(selected_area="Psicoterapia", focus=["Autismo"])
    patient = Patient(1, "Psicoterapia", matching_request=request)
    specialized = professional_profile(areas=["Psicoterapia"], focus=["Autismo"])
    other_specialty = professional_profile(areas=["Psicoterapia"], focus=["Depressão"])

    assert compatibility(patient, cycle(matching_profile=specialized)) == 1
    assert compatibility(patient, cycle(matching_profile=other_specialty)) == 0
    assert score_candidate(patient, cycle(matching_profile=other_specialty), REFERENCE_TIME) is not None


def test_legacy_specialty_names_are_stored_with_canonical_names():
    profile = professional_profile(
        areas=["Psicoterapia"],
        focus=["Bipolaridade", "Borderline"],
    )

    assert profile["psychotherapy"]["specialties"] == [
        "Transtorno Bipolar",
        "Transtorno de Personalidade Borderline",
    ]


def test_arbitrary_specialties_and_aliases_match_existing_json_without_rewriting_it():
    request = patient_request(selected_area="Psicoterapia", focus=["Boderline", "Luto prolongado"])
    profile = professional_profile(areas=["Psicoterapia"])
    profile["psychotherapy"]["specialties"] = ["borderline", "  LUTO   PROLONGADO "]
    patient = Patient(1, "Psicoterapia", matching_request=request)
    assert compatibility(patient, cycle(matching_profile=profile)) == 1
    assert request["psychotherapy"]["specialties"] == ["Transtorno de Personalidade Borderline", "Luto prolongado"]
    assert profile["psychotherapy"]["specialties"] == ["borderline", "  LUTO   PROLONGADO "]


@pytest.mark.parametrize("legacy_preference", [True, False, None])
def test_lgbt_identity_is_ignored_even_in_existing_requests(legacy_preference):
    request = patient_request(selected_area="Psicoterapia", prefers_lgbtqiapn_plus=legacy_preference)
    patient = Patient(1, "Psicoterapia", matching_request=request)
    for identity in (True, False, None):
        profile = professional_profile(areas=["Psicoterapia"], lgbtqiapn_plus=identity)
        candidate = cycle(matching_profile=profile)
        assert compatibility(patient, candidate) == 0
        score = score_candidate(patient, candidate, REFERENCE_TIME)
        assert score is not None
        assert score.breakdown.preferences is not None
        assert "lgbtqiapn_plus" not in score.breakdown.preferences["requested"]
        assert "lgbtqiapn_plus" not in score.breakdown.preferences["matched"]


def test_lgbt_specialty_matches_expertise_independently_of_identity():
    patient = Patient(1, "Psicoterapia", matching_request=patient_request(selected_area="Psicoterapia", focus=["LGBTQIAPN+"]))
    identity_only = professional_profile(areas=["Psicoterapia"], lgbtqiapn_plus=True)
    specialist = professional_profile(areas=["Psicoterapia"], focus=["lgbtqiapn+"], lgbtqiapn_plus=False)
    assert compatibility(patient, cycle(matching_profile=identity_only)) == 0
    assert compatibility(patient, cycle(matching_profile=specialist)) == 1
    assert score_candidate(patient, cycle(matching_profile=identity_only), REFERENCE_TIME) is not None


@pytest.mark.parametrize(("requested", "offered"), [("Negro", "Negra"), ("Branco", "Branca"), ("Asiático", "Asiática"),
                                                    ("Indígena", "indigena"), ("Imigrante", "imigrante")])
def test_self_declaration_aliases_match(requested, offered):
    request = patient_request(selected_area="Psicoterapia", preferred_race=requested, preferred_gender="Não binário")
    profile = professional_profile(areas=["Psicoterapia"], race=offered, gender="Não binária")
    assert compatibility(Patient(1, "Psicoterapia", matching_request=request), cycle(matching_profile=profile)) == 2


@pytest.mark.parametrize(("days", "expected"), [(10, 1), (7, 4), (1, 1000)])
def test_urgency_curve_targets(days: int, expected: float):
    assert urgency_score(days * 86400) == pytest.approx(expected)


def test_urgency_overtakes_up_to_three_optional_preferences():
    request = patient_request(selected_area="Psicoterapia", focus=["Ansiedade"],
                              preferred_gender="Mulher", preferred_race="Negra",
                              prefers_lgbtqiapn_plus=True)
    patient = Patient(1, "Psicoterapia", matching_request=request)
    full_profile = professional_profile(areas=["Psicoterapia"], focus=["Ansiedade"],
                                        gender="Mulher", race="Negra", lgbtqiapn_plus=True)
    empty_profile = professional_profile(areas=["Psicoterapia"])
    preferred = cycle(id=1, matching_profile=full_profile,
                      deadline_at=REFERENCE_TIME + timedelta(days=10))
    urgent = cycle(id=2, matching_profile=empty_profile,
                   deadline_at=REFERENCE_TIME + timedelta(days=7))
    assert compatibility(patient, preferred) == 3
    assert [c.id for c, _ in rank(patient, [preferred, urgent], REFERENCE_TIME)] == [2, 1]

    urgent.deadline_at = REFERENCE_TIME + timedelta(days=5)
    assert [c.id for c, _ in rank(patient, [preferred, urgent], REFERENCE_TIME)] == [2, 1]
    scored = score_candidate(patient, urgent, REFERENCE_TIME)
    assert scored is not None
    assert scored.final == pytest.approx(scored.urgency + scored.compatibility)


@pytest.mark.parametrize("year", [2000, 2020, 2100])
def test_tie_break_is_independent_of_calendar_date(year):
    clock = datetime(year, 1, 1, tzinfo=UTC)
    patient = Patient(1, "Psicoterapia")
    candidates = [cycle(id=i, starts_at=clock-timedelta(days=1),
                        deadline_at=clock+timedelta(days=days)) for i, days in [(1, 20), (2, 8), (3, 7), (4, 2)]]
    assert [c.id for c, _ in rank(patient, candidates, clock)] == [4, 3, 2, 1]


@pytest.mark.parametrize("changes", [
    {"area": "Nutrição"}, {"deadline_at": REFERENCE_TIME},
    {"deadline_at": REFERENCE_TIME - timedelta(seconds=1)},
    {"starts_at": REFERENCE_TIME + timedelta(seconds=1)},
    {"cancelled_at": REFERENCE_TIME}, {"used": 1},
])
def test_ineligible(changes):
    assert score_candidate(Patient(1, "Psicoterapia"), cycle(**changes), REFERENCE_TIME) is None


def test_psychoanalysis_legacy_area_is_psychotherapy():
    assert score_candidate(Patient(1, "Psicoterapia"),
                           cycle(area="Psicanálise", approach=None), REFERENCE_TIME) is not None
    assert score_candidate(Patient(1, "Psicoterapia", "Psicanálise"),
                           cycle(area="Psicanálise", approach=None), REFERENCE_TIME) is not None


def test_replacement_has_identical_priority():
    patient = Patient(1, "Psicoterapia")
    assert score_candidate(patient, cycle(type="REGULAR"), REFERENCE_TIME) == score_candidate(
        patient, cycle(type="REPLACEMENT"), REFERENCE_TIME)
