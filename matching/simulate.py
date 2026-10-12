"""Reproducible simulation: python -m matching.simulate --seeds 100."""
import argparse
import json
import random
import statistics
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.matching import Candidate, Patient
from app.domain.matching.profile import patient_request, professional_profile
from matching.domain import rank, requirements_met


def simulate(seed: int, professionals: int = 50, patients: int = 500) -> dict[str, Any]:
    rng = random.Random(seed)  # noqa: S311
    now = datetime(2026, 1, 1, tzinfo=UTC)
    areas = ["Psicoterapia", "Nutrição", "Psiquiatria"]
    cycles: list[Candidate] = []
    for index in range(professionals):
        offered = rng.sample(areas, k=2 if rng.random() < 0.15 else 1)
        approach = rng.choice(["TCC", "Psicanálise", None]) if "Psicoterapia" in offered else None
        profile = professional_profile(
            areas=offered, approaches=[approach] if approach else [],
            focus=rng.sample(["Ansiedade", "Depressão", "TDAH"], k=rng.randint(0, 2)),
            gender=rng.choice(["Mulher", "Homem", None]),
        )
        cycles.append(Candidate(
            id=index, area=offered[0], matching_profile=profile,
            starts_at=now + timedelta(days=rng.randint(-30, 2)),
            deadline_at=now + timedelta(days=rng.randint(-2, 30)),
            cancelled_at=now if rng.random() < 0.05 else None,
            promised_patients=rng.randint(1, 12), used=0,
            type=rng.choice(["REGULAR", "REPLACEMENT"]),
        ))
    population: list[Patient] = []
    for index in range(patients):
        wanted_area = rng.choice(areas)
        wanted_approach = rng.choice(["TCC", "Psicanálise", None]) if wanted_area == "Psicoterapia" else None
        request = patient_request(
            selected_area=wanted_area, selected_approach=wanted_approach,
            focus=[rng.choice(["Ansiedade", "Depressão", "TDAH"])] if rng.random() < 0.3 else None,
            preferred_gender=rng.choice(["Mulher", "Homem", None]),
        )
        population.append(Patient(id=index, area=wanted_area, matching_request=request))
    compatibilities: list[float] = []
    assigned: set[int] = set()
    urgent = 0
    start = time.perf_counter()
    for patient in population:
        choices = rank(patient, cycles, now)
        if not choices:
            continue
        cycle, score = choices[0]
        if patient.id in assigned or not requirements_met(patient, cycle) or cycle.deadline_at <= now:
            raise AssertionError(f"Invalid allocation seed={seed} patient={patient.id}")
        assigned.add(patient.id)
        cycle.used += 1
        if cycle.used > cycle.promised_patients:
            raise AssertionError(f"Overbooking seed={seed}")
        compatibilities.append(score.compatibility)
        urgent += score.breakdown.phase == "urgent"
    eligible = [cycle for cycle in cycles if cycle.starts_at <= now < cycle.deadline_at and not cycle.cancelled_at]
    capacity = sum(cycle.promised_patients for cycle in eligible)
    return {
        "seed": seed, "matched": len(assigned), "pending": patients-len(assigned),
        "fill_rate": len(assigned)/capacity if capacity else 0,
        "unfilled_capacity": max(0, capacity-len(assigned)),
        "mean_compatibility": statistics.mean(compatibilities) if compatibilities else 0,
        "urgent_matches": urgent, "elapsed_ms": (time.perf_counter()-start)*1000,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--professionals", type=int, default=50)
    parser.add_argument("--patients", type=int, default=500)
    args = parser.parse_args()
    for seed in range(args.seeds):
        print(json.dumps(simulate(seed, args.professionals, args.patients)))
