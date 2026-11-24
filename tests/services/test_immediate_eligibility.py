from datetime import UTC, datetime

from app.domain.db.professional_model import ProfessionalModel
from app.domain.immediate_eligibility import is_eligible_for_immediate, is_psychologist


def professional(
    *, area: str = "Psicoterapia", register_type: str = "CRP", areas: list[str] | None = None, released: bool = True
) -> ProfessionalModel:
    found = ProfessionalModel(
        id=1,
        person_id=1,
        area=area,
        professional_register="1",
        register_type=register_type,
        matching_profile={"areas": areas} if areas is not None else {},
    )
    found.immediate_approved_at = datetime(2026, 11, 12, tzinfo=UTC) if released else None
    return found


def test_psychologist_by_canonical_profile_areas():
    assert is_psychologist(professional(area="Nutrição", areas=["Psicoterapia", "Nutrição"])) is True
    assert is_psychologist(professional(area="Psicoterapia", areas=["Nutrição"])) is False


def test_psychologist_by_legacy_area_with_aliases_and_commas():
    assert is_psychologist(professional(area="Psicoterapia, Psiquiatria")) is True
    assert is_psychologist(professional(area="Psicanálise")) is True
    assert is_psychologist(professional(area="psicoterapia tcc")) is True
    assert is_psychologist(professional(area="Nutrição")) is False


def test_only_psychologists_released_by_the_team_are_eligible():
    assert is_eligible_for_immediate(professional()) is True
    assert is_eligible_for_immediate(professional(area="Nutrição")) is False
    # register_type comes from the public registration body: "CRP" there proves nothing.
    assert is_eligible_for_immediate(professional(register_type="CRP", released=False)) is False
    assert is_eligible_for_immediate(professional(register_type="PENDING_REVIEW", released=False)) is False
