from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.domain.matching import Candidate, Patient
from app.domain.matching.profile import patient_request, professional_profile
from matching.domain import compatibility, rank, score_candidate

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
    assert compatibility(patient, cycle(matching_profile=profile)) == 4
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


def test_more_optional_matches_precede_earlier_deadline():
    patient = Patient(1, "Psicoterapia", "TCC", "Mulher negra")
    earlier = cycle(id=1, gender="Homem", minority_group=None,
                    deadline_at=REFERENCE_TIME + timedelta(days=1))
    later = cycle(id=2, deadline_at=REFERENCE_TIME + timedelta(days=3))
    assert [c.id for c, _ in rank(patient, [earlier, later], REFERENCE_TIME)] == [2, 1]


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
