"""Greedy exact-area matching; optional preference scoring is disabled."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ALGORITHM_VERSION = "area-greedy-v1"
WINDOW_SECONDS = 7 * 86400


def compatibility(patient: dict[str, Any], professional: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Extension point for future preference scoring (e.g. categorical cosine).

    Preferences are intentionally disabled: only exact area and cycle eligibility
    influence matching. Do not infer compatibility from gender or approach yet.
    """
    return 0.0, {"preferences_enabled": False}


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
    final = urgency  # Preferences are disabled; greedily fill the nearest deadline.
    details.update(phase="urgent" if urgent else "normal", evaluated_at=now.isoformat(),
                   area=patient["area"], deadline_at=candidate["deadline_at"].isoformat(),
                   tie_break="deadline,cycle_id")
    return Score(comp, urgency, final, details)


def rank(patient: dict[str, Any], candidates: list[dict[str, Any]], now: datetime) -> list[tuple[dict[str, Any], Score]]:
    scored = [(c, s) for c in candidates if (s := score_candidate(patient, c, now)) is not None]
    return sorted(scored, key=lambda pair: (pair[0]["deadline_at"], pair[0]["id"]))
