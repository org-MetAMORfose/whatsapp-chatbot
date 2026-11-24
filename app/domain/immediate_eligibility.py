"""Who may take immediate care sessions: psychologists the team released in the panel.

`register_type` cannot be the gate: the public registration endpoint accepts it from the request body.
`immediate_approved_at` is written only by the panel through the authenticated endpoint, after the
team checks the professional's CRP.
"""
from __future__ import annotations

from app.domain.db.professional_model import ProfessionalModel
from app.domain.matching.profile import PSYCHOTHERAPY, area

PENDING_REVIEW = "PENDING_REVIEW"


def _areas(professional: ProfessionalModel) -> list[str]:
    profile = professional.matching_profile if isinstance(professional.matching_profile, dict) else {}
    listed = profile.get("areas")
    if isinstance(listed, list) and listed:
        return [str(value) for value in listed]
    return (professional.area or "").split(",")


def is_psychologist(professional: ProfessionalModel) -> bool:
    """Canonical profile areas first; legacy comma-separated `area` strings and aliases as a fallback."""
    return any(area(value) == PSYCHOTHERAPY for value in _areas(professional))


def is_released_for_immediate(professional: ProfessionalModel) -> bool:
    return professional.immediate_approved_at is not None


def is_eligible_for_immediate(professional: ProfessionalModel) -> bool:
    return is_released_for_immediate(professional) and is_psychologist(professional)
