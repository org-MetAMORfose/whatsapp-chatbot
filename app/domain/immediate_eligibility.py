"""Who may take immediate care sessions: professionals of any area the team released in the panel.

`register_type` cannot be the gate: the public registration endpoint accepts it from the request body.
`immediate_approved_at` is written only by the panel through the authenticated endpoint, after the
team checks the professional's register.
"""
from __future__ import annotations

from app.domain.db.professional_model import ProfessionalModel
from app.domain.matching.profile import area, key

PENDING_REVIEW = "PENDING_REVIEW"


def _areas(professional: ProfessionalModel) -> list[str]:
    profile = professional.matching_profile if isinstance(professional.matching_profile, dict) else {}
    listed = profile.get("areas")
    if isinstance(listed, list) and listed:
        return [str(value) for value in listed]
    return (professional.area or "").split(",")


def works_in_area(professional: ProfessionalModel, wanted: str | None) -> bool:
    """Canonical profile areas first; legacy comma-separated `area` strings and aliases as a fallback.

    A request without an area (created before the patient was asked) is open to every area.
    """
    target = area(wanted)
    if target is None:
        return True
    return any(key(area(value)) == key(target) for value in _areas(professional))


def is_released_for_immediate(professional: ProfessionalModel) -> bool:
    return professional.immediate_approved_at is not None


def is_eligible_for_immediate(professional: ProfessionalModel) -> bool:
    return is_released_for_immediate(professional)
