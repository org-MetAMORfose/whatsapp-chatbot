"""Hard requirements and optional preference ranking for matching."""
from datetime import datetime
from typing import Any

from app.domain.matching import Candidate, Patient, Score, ScoreBreakdown
from app.domain.matching.profile import PSYCHOTHERAPY, area, declaration, key, normalize_gender, patient_request, professional_profile, specialties

ALGORITHM_VERSION = "specialty-preferences-urgency-v3"
WINDOW_SECONDS = 7 * 86400
DAY_SECONDS = 86400


def urgency_score(remaining_seconds: float) -> float:
    """Grow slowly until day seven, then accelerate toward the deadline."""
    days = remaining_seconds / DAY_SECONDS
    acceleration = (max(0.0, 7.0 - days) / 6.0) ** 2
    return float(4 ** ((10.0 - days) / 3.0) * (1000.0 / 64.0) ** acceleration)


def _request(patient: Patient) -> dict[str, Any]:
    return patient.matching_request or patient_request(
        selected_area=patient.area,
        selected_approach=patient.psychotherapy_approach,
        professional_profile=patient.professional_profile,
    )


def _profile(candidate: Candidate) -> dict[str, Any]:
    return candidate.matching_profile or professional_profile(
        areas=[candidate.area], approaches=[candidate.approach] if candidate.approach else [],
        gender=candidate.gender, minority_group=candidate.minority_group,
    )


def requirements_met(patient: Patient, candidate: Candidate) -> bool:
    request = _request(patient)
    profile = _profile(candidate)
    requested_area = area(request.get("area"))
    if requested_area is None or requested_area not in profile.get("areas", []):
        return False
    if requested_area == PSYCHOTHERAPY:
        chosen = (request.get("psychotherapy") or {}).get("approach")
        offered = (profile.get("psychotherapy") or {}).get("approaches") or []
        if chosen and chosen not in offered:
            return False
    return True


def preference_details(patient: Patient, candidate: Candidate) -> dict[str, bool | None]:
    request = _request(patient)
    profile = _profile(candidate)
    wanted = request.get("professional_preferences") or {}
    actual = profile.get("profile") or {}
    requested_focus = {key(value) for value in specialties((request.get("psychotherapy") or {}).get("specialties"))}
    offered_focus = {key(value) for value in specialties((profile.get("psychotherapy") or {}).get("specialties"))}
    details: dict[str, bool | None] = {
        "specialties": bool(requested_focus & offered_focus) if requested_focus else None,
    }
    for field, normalize in (("gender", normalize_gender), ("race", declaration)):
        preferred = normalize(wanted.get(field))
        value = normalize(actual.get(field))
        if preferred is None:
            details[field] = None
        elif value is None:
            details[field] = False
        elif field == "gender" and key(preferred) in ("mulher", "homem"):
            details[field] = key(value) in (key(preferred), key(preferred) + " trans")
        else:
            details[field] = key(str(preferred)) == key(str(value))
    return details


def compatibility(patient: Patient, professional: Candidate) -> float:
    details = preference_details(patient, professional)
    return float(sum(matched is True for matched in details.values()))


def score_candidate(patient: Patient, candidate: Candidate, now: datetime) -> Score | None:
    if not requirements_met(patient, candidate):
        return None
    remaining = (candidate.deadline_at - now).total_seconds()
    if candidate.cancelled_at or candidate.starts_at > now or remaining <= 0:
        return None
    if candidate.used >= candidate.promised_patients:
        return None
    urgency = urgency_score(remaining)
    details = preference_details(patient, candidate)
    score = compatibility(patient, candidate)
    request = _request(patient)
    return Score(score, urgency, score + urgency, ScoreBreakdown(
        phase="urgent" if remaining <= WINDOW_SECONDS else "normal", evaluated_at=now.isoformat(),
        area=request["area"], deadline_at=candidate.deadline_at.isoformat(),
        preferences_enabled=True, tie_break="final_score,deadline,cycle_id",
        preferences={
            "requested": {
                "specialties": (request.get("psychotherapy") or {}).get("specialties") or [],
                **{field: (request.get("professional_preferences") or {}).get(field) for field in ("gender", "race")},
            },
            "matched": details,
        },
        required={"area": request["area"],
                  "approach": (request.get("psychotherapy") or {}).get("approach") or "sem preferência"},
    ))


def rank(patient: Patient, candidates: list[Candidate], now: datetime) -> list[tuple[Candidate, Score]]:
    scored = [(candidate, score) for candidate in candidates
              if (score := score_candidate(patient, candidate, now)) is not None]
    return sorted(scored, key=lambda pair: (-pair[1].final, pair[0].deadline_at, pair[0].id))
