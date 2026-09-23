from datetime import UTC, datetime, timedelta
from random import Random
from typing import Any

import pytest

from matching.domain import compatibility, rank, score_candidate

NOW = datetime(2026, 9, 23, tzinfo=UTC)


def cycle(**changes: Any) -> dict[str, Any]:
    base = dict(  # noqa: C408
        id=1, area="Psicoterapia", approach="TCC", gender="Mulher", minority_group="Negro LGBT",
                     starts_at=NOW - timedelta(days=30), deadline_at=NOW + timedelta(days=20),
                     cancelled_at=None, promised_patients=1, used=0)  # noqa: C408
    return {**base, **changes}


def test_categorical_cosine_masks_unspecified_attributes():
    p = {"area": "Psicoterapia", "psychotherapy_approach": "TCC"}
    assert compatibility(p, cycle())[0] == 1
    p["professional_profile"] = "Mulher negra"
    assert compatibility(p, cycle())[0] == pytest.approx(1)
    assert compatibility(p, cycle(gender="Homem"))[0] == pytest.approx(2 / 3)
    assert compatibility({"area": "Nutrição"}, cycle())[0] == 0


def test_urgent_overrides_compatibility_but_normal_prefers_it():
    p = {"area": "Psicoterapia", "psychotherapy_approach": "TCC"}
    weaker = cycle(id=2, approach="Psicanálise", deadline_at=NOW + timedelta(days=8))
    assert rank(p, [weaker, cycle()], NOW)[0][0]["id"] == 1
    weaker["deadline_at"] = NOW + timedelta(days=7)
    assert rank(p, [cycle(), weaker], NOW)[0][0]["id"] == 2
    assert rank(p, [cycle(deadline_at=NOW + timedelta(days=6)), weaker], NOW)[0][0]["id"] == 1


@pytest.mark.parametrize("changes", [
    {"area": "Psicanálise"}, {"deadline_at": NOW}, {"deadline_at": NOW - timedelta(seconds=1)},
    {"starts_at": NOW + timedelta(seconds=1)}, {"cancelled_at": NOW}, {"used": 1},
])
def test_ineligible(changes):
    assert score_candidate({"area": "Psicoterapia"}, cycle(**changes), NOW) is None


def test_seeded_simulation():
    """50 reproducible populations: 40 professionals/cycles and 300 patients."""
    for seed in range(50):
        rng = Random(seed)  # noqa: S311
        areas = ["Psicoterapia", "Psicanálise", "Nutrição"]
        cycles = [cycle(id=i, area=rng.choice(areas), approach=rng.choice(["TCC", "Psicanálise"]),
                        type=rng.choice(["REGULAR", "REPLACEMENT"]), promised_patients=rng.randint(1, 10),
                        deadline_at=NOW + timedelta(days=rng.randint(-3, 30))) for i in range(40)]
        assigned = set()
        for patient_id in range(300):
            patient = {"area": rng.choice(areas), "psychotherapy_approach": rng.choice(["TCC", "Psicanálise", None])}
            ranked = rank(patient, cycles, NOW)
            if not ranked:
                continue
            candidate, score = ranked[0]
            assert patient_id not in assigned
            assigned.add(patient_id)
            assert candidate["area"] == patient["area"]
            assert candidate["deadline_at"] > NOW
            assert score.compatibility <= 1
            if any((c["deadline_at"] - NOW).days < 7 for c, _ in ranked):
                assert score.breakdown["phase"] == "urgent"
            candidate["used"] += 1
        assert all(c["used"] <= c["promised_patients"] for c in cycles), seed


def test_replacement_has_identical_priority():
    p = {"area": "Psicoterapia"}
    assert score_candidate(p, cycle(type="REGULAR"), NOW) == score_candidate(p, cycle(type="REPLACEMENT"), NOW)


def test_simulation_reports_optimal_fill_for_area_only_hard_filter():
    from matching.simulate import simulate
    for seed in range(10):
        metrics = simulate(seed)
        assert metrics["avoidable_unfilled"] == 0
        assert 0 <= metrics["fill_rate"] <= 1
