"""Greedy exact-area matching; optional preference scoring is disabled."""
from datetime import datetime

from app.domain.matching import Candidate, Patient, Score, ScoreBreakdown

ALGORITHM_VERSION = "area-greedy-v1"
WINDOW_SECONDS = 7 * 86400


def compatibility(patient: Patient, professional: Candidate) -> float:
    """Extension point for future preferences; currently no preference affects selection."""
    return 0.0


def score_candidate(patient: Patient, candidate: Candidate, now: datetime) -> Score | None:
    if not patient.area or patient.area != candidate.area:
        return None
    remaining = (candidate.deadline_at - now).total_seconds()
    if candidate.cancelled_at or candidate.starts_at > now or remaining <= 0:
        return None
    if candidate.used >= candidate.promised_patients:
        return None
    urgency = WINDOW_SECONDS / (WINDOW_SECONDS + remaining)
    return Score(compatibility(patient, candidate), urgency, urgency, ScoreBreakdown(
        phase="urgent" if remaining <= WINDOW_SECONDS else "normal", evaluated_at=now.isoformat(),
        area=patient.area, deadline_at=candidate.deadline_at.isoformat()))


def rank(patient: Patient, candidates: list[Candidate], now: datetime) -> list[tuple[Candidate, Score]]:
    scored = [(c, s) for c in candidates if (s := score_candidate(patient, c, now)) is not None]
    return sorted(scored, key=lambda pair: (pair[0].deadline_at, pair[0].id))
