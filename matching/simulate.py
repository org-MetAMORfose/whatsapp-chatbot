"""Reproducible simulation: python -m matching.simulate --seeds 100."""
import argparse
import json
import random
import statistics
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from matching.domain import rank


def simulate(seed: int, professionals: int = 50, patients: int = 500) -> dict[str, Any]:
    rng = random.Random(seed)  # noqa: S311
    now = datetime(2026, 1, 1, tzinfo=UTC)
    areas = ["Psicoterapia", "Nutrição", "Psiquiatria", "Psicanálise"]
    cycles: list[dict[str, Any]] = [{"id": i, "area": rng.choice(areas), "approach": rng.choice(["TCC", "Psicanálise", None]),
               "gender": rng.choice(["Mulher", "Homem", "Mulher trans", None]),
               "minority_group": rng.choice(["Negro", "LGBT", "Negro LGBT", None]),
               "starts_at": now + timedelta(days=rng.randint(-30, 2)),
               "deadline_at": now + timedelta(days=rng.randint(-2, 30)),
               "cancelled_at": now if rng.random() < 0.05 else None,
               "promised_patients": rng.randint(1, 12), "used": 0,
               "type": rng.choice(["REGULAR", "REPLACEMENT"])} for i in range(professionals)]
    population: list[dict[str, Any]] = [{"id": i, "area": rng.choice(areas), "psychotherapy_approach": rng.choice(["TCC", "Psicanálise", None]),
                   "professional_profile": rng.choice(["Mulher", "Mulher negra", "LGBTQIAPN+", None])} for i in range(patients)]
    compatibilities: list[float] = []
    assigned: set[int] = set()
    urgent = 0
    start = time.perf_counter()
    for patient in population:
        choices = rank(patient, cycles, now)
        if not choices:
            continue
        cycle, score = choices[0]
        if patient["id"] in assigned or cycle["area"] != patient["area"] or cycle["deadline_at"] <= now:
            raise AssertionError(f"Invalid allocation seed={seed} patient={patient['id']}")
        assigned.add(patient["id"])
        cycle["used"] += 1
        if cycle["used"] > cycle["promised_patients"]:
            raise AssertionError(f"Overbooking seed={seed}")
        compatibilities.append(score.compatibility)
        urgent += score.breakdown["phase"] == "urgent"
    eligible = [c for c in cycles if c["starts_at"] <= now < c["deadline_at"] and not c["cancelled_at"]]
    capacity = sum(c["promised_patients"] for c in eligible)
    # Exact maximum cardinality for this model: area is the sole pairwise hard criterion.
    optimum = sum(min(sum(p["area"] == area for p in population),
                      sum(c["promised_patients"] for c in eligible if c["area"] == area)) for area in areas)
    return {"seed": seed, "matched": len(assigned), "pending": patients-len(assigned),
            "fill_rate": len(assigned)/capacity if capacity else 0, "avoidable_unfilled": optimum-len(assigned),
            "mean_compatibility": statistics.mean(compatibilities) if compatibilities else 0,
            "urgent_matches": urgent, "elapsed_ms": (time.perf_counter()-start)*1000}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--professionals", type=int, default=50)
    parser.add_argument("--patients", type=int, default=500)
    args = parser.parse_args()
    for seed in range(args.seeds):
        print(json.dumps(simulate(seed, args.professionals, args.patients)))
