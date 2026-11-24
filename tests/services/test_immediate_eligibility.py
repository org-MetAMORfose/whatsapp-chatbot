from datetime import UTC, datetime

from app.domain.db.professional_model import ProfessionalModel
from app.domain.immediate_eligibility import is_eligible_for_immediate, works_in_area


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


def test_area_by_canonical_profile_areas():
    assert works_in_area(professional(area="Nutrição", areas=["Psicoterapia", "Nutrição"]), "Psicoterapia") is True
    assert works_in_area(professional(area="Psicoterapia", areas=["Nutrição"]), "Psicoterapia") is False
    assert works_in_area(professional(area="Psicoterapia", areas=["Nutrição"]), "nutricao") is True


def test_area_by_legacy_text_with_aliases_and_commas():
    assert works_in_area(professional(area="Psicoterapia, Psiquiatria"), "Psiquiatria") is True
    assert works_in_area(professional(area="Psicanálise"), "psicoterapia") is True
    assert works_in_area(professional(area="psicoterapia tcc"), "Psicoterapia") is True
    assert works_in_area(professional(area="Nutrição"), "Psicoterapia") is False
    assert works_in_area(professional(area="Nutricionista"), "Nutrição") is True
    assert works_in_area(professional(area="Clínico Geral"), "clinico geral") is True


def test_a_request_without_area_is_open_to_every_area():
    """Requests created before the area question existed."""
    assert works_in_area(professional(area="Nutrição"), None) is True
    assert works_in_area(professional(area="Nutrição"), "  ") is True


def test_every_professional_released_by_the_team_is_eligible():
    assert is_eligible_for_immediate(professional()) is True
    assert is_eligible_for_immediate(professional(area="Nutrição")) is True
    # register_type comes from the public registration body: "CRP" there proves nothing.
    assert is_eligible_for_immediate(professional(register_type="CRP", released=False)) is False
    assert is_eligible_for_immediate(professional(register_type="PENDING_REVIEW", released=False)) is False
