from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any

import pytest

from matching.domain import compatibility, rank, score_candidate

REFERENCE_TIME = datetime(2000, 1, 1, tzinfo=UTC)  # Injected clock; independent of the execution date.


def cycle(**changes: Any) -> dict[str, Any]:
    base = dict(  # noqa: C408
        id=1, area="Psicoterapia", approach="TCC", gender="Mulher", minority_group="Negro LGBT",
                     starts_at=REFERENCE_TIME - timedelta(days=30), deadline_at=REFERENCE_TIME + timedelta(days=20),
                     cancelled_at=None, promised_patients=1, used=0)  # noqa: C408
    return {**base, **changes}


def test_preferences_are_disabled():
    patient = {"area": "Psicoterapia", "psychotherapy_approach": "TCC", "professional_profile": "Mulher negra"}
    assert compatibility(patient, cycle())[0] == 0
    assert compatibility(patient, cycle(gender="Homem", approach="Psicanálise"))[0] == 0


@pytest.mark.parametrize("year", [2000, 2020, 2100])
def test_greedy_order_is_independent_of_calendar_date(year):
    clock = datetime(year, 1, 1, tzinfo=UTC)
    patient = {"area": "Psicoterapia", "psychotherapy_approach": "TCC"}
    candidates = [cycle(id=i, starts_at=clock-timedelta(days=1), deadline_at=clock+timedelta(days=days))
                  for i, days in [(1, 20), (2, 8), (3, 7), (4, 2)]]
    assert [c["id"] for c, _ in rank(patient, candidates, clock)] == [4, 3, 2, 1]
    assert all(score.compatibility == 0 for _, score in rank(patient, candidates, clock))


@pytest.mark.parametrize("changes", [
    {"area": "Psicanálise"}, {"deadline_at": REFERENCE_TIME}, {"deadline_at": REFERENCE_TIME - timedelta(seconds=1)},
    {"starts_at": REFERENCE_TIME + timedelta(seconds=1)}, {"cancelled_at": REFERENCE_TIME}, {"used": 1},
])
def test_ineligible(changes):
    assert score_candidate({"area": "Psicoterapia"}, cycle(**changes), REFERENCE_TIME) is None


def test_seeded_simulation():
    """50 reproducible populations: 40 professionals/cycles and 300 patients."""
    for seed in range(50):
        rng = Random(seed)  # noqa: S311
        areas = ["Psicoterapia", "Psicanálise", "Nutrição"]
        cycles = [cycle(id=i, area=rng.choice(areas), approach=rng.choice(["TCC", "Psicanálise"]),
                        type=rng.choice(["REGULAR", "REPLACEMENT"]), promised_patients=rng.randint(1, 10),
                        deadline_at=REFERENCE_TIME + timedelta(days=rng.randint(-3, 30))) for i in range(40)]
        assigned = set()
        for patient_id in range(300):
            patient = {"area": rng.choice(areas), "psychotherapy_approach": rng.choice(["TCC", "Psicanálise", None])}
            ranked = rank(patient, cycles, REFERENCE_TIME)
            if not ranked:
                continue
            candidate, score = ranked[0]
            assert patient_id not in assigned
            assigned.add(patient_id)
            assert candidate["area"] == patient["area"]
            assert candidate["deadline_at"] > REFERENCE_TIME
            assert score.compatibility <= 1
            if any((c["deadline_at"] - REFERENCE_TIME).days < 7 for c, _ in ranked):
                assert score.breakdown["phase"] == "urgent"
            candidate["used"] += 1
        assert all(c["used"] <= c["promised_patients"] for c in cycles), seed


def test_replacement_has_identical_priority():
    p = {"area": "Psicoterapia"}
    assert score_candidate(p, cycle(type="REGULAR"), REFERENCE_TIME) == score_candidate(p, cycle(type="REPLACEMENT"), REFERENCE_TIME)


def test_simulation_reports_optimal_fill_for_area_only_hard_filter():
    from matching.simulate import simulate
    for seed in range(10):
        metrics = simulate(seed)
        assert metrics["avoidable_unfilled"] == 0
        assert 0 <= metrics["fill_rate"] <= 1
