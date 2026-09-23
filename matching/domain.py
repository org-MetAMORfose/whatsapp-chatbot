"""Deterministic categorical cosine; no embeddings, network or database calls."""
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Any

ALGORITHM_VERSION = "categorical-cosine-v1"
WINDOW_SECONDS = 7 * 86400
NORMAL_DEADLINE_WEIGHT = 0.1


def preference(value: str | None) -> str | None:
    if value in (None, "", "Sem preferência", "Prefiro não informar"):
        return None
    return value


def compatibility(patient: dict[str, Any], professional: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Each requested criterion contributes a unit categorical vector.

    Extra professional attributes are masked out. All blocks have equal weight;
    a mismatch is an orthogonal vector, not a missing/zero vector.
    """
    criteria: dict[str, bool] = {}
    if patient["area"] == "Psicoterapia" and (approach := preference(patient.get("psychotherapy_approach"))):
        criteria["approach"] = approach == professional.get("approach")
    profile = preference(patient.get("professional_profile"))
    gender = professional.get("gender")
    group = professional.get("minority_group")
    if profile:
        if profile in ("Mulher", "Mulher negra"):
            criteria["gender"] = gender in ("Mulher", "Mulher trans")
        elif profile == "Homem negro":
            criteria["gender"] = gender in ("Homem", "Homem trans")
        if profile in ("Mulher negra", "Homem negro"):
            criteria["race"] = group in ("Negro", "Negro LGBT")
        elif profile == "LGBTQIAPN+":
            criteria["lgbt"] = group in ("LGBT", "Negro LGBT") or gender in ("Mulher trans", "Homem trans")
        elif profile not in ("Mulher", "Mulher negra", "Homem negro"):
            criteria["unknown_profile"] = False
    n = len(criteria)
    score = sum(criteria.values()) / (sqrt(n) * sqrt(n)) if n else 0.0
    return min(1.0, score), {"criteria": criteria, "no_preference": not criteria}


@dataclass(frozen=True)
class Score:
    compatibility: float
    urgency: float
    final: float
    breakdown: dict[str, Any]


def score_candidate(patient: dict[str, Any], candidate: dict[str, Any], now: datetime) -> Score | None:
    if not patient.get("area") or patient["area"] != candidate["area"]:
        return None
    remaining = (candidate["deadline_at"] - now).total_seconds()
    if candidate.get("cancelled_at") or candidate["starts_at"] > now or remaining <= 0:
        return None
    if candidate["used"] >= candidate["promised_patients"]:
        return None
    comp, details = compatibility(patient, candidate)
    urgent = remaining <= WINDOW_SECONDS
    urgency = WINDOW_SECONDS / (WINDOW_SECONDS + remaining)
    final = 2 + urgency if urgent else comp + NORMAL_DEADLINE_WEIGHT * urgency
    details.update(phase="urgent" if urgent else "normal", evaluated_at=now.isoformat(),
                   area=patient["area"], window_seconds=WINDOW_SECONDS, deadline_weight=NORMAL_DEADLINE_WEIGHT,
                   patient_preferences={key: patient.get(key) for key in ("psychotherapy_approach", "professional_profile")},
                   professional_attributes={key: candidate.get(key) for key in ("approach", "gender", "minority_group")},
                   deadline_at=candidate["deadline_at"].isoformat(), tie_break="compatibility,deadline,cycle_id")
    return Score(comp, urgency, final, details)


def rank(patient: dict[str, Any], candidates: list[dict[str, Any]], now: datetime) -> list[tuple[dict[str, Any], Score]]:
    scored = [(c, s) for c in candidates if (s := score_candidate(patient, c, now)) is not None]
    return sorted(scored, key=lambda pair: (-pair[1].final, -pair[1].compatibility, pair[0]["deadline_at"], pair[0]["id"]))
