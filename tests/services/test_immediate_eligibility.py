from app.domain.db.professional_model import ProfessionalModel
from app.domain.immediate_eligibility import PENDING_REVIEW, is_eligible_for_immediate, is_psychologist


def professional(*, area: str = "Psicoterapia", register_type: str = "CRP", areas: list[str] | None = None) -> ProfessionalModel:
    return ProfessionalModel(
        id=1,
        person_id=1,
        area=area,
        professional_register="1",
        register_type=register_type,
        matching_profile={"areas": areas} if areas is not None else {},
    )


def test_psychologist_by_canonical_profile_areas():
    assert is_psychologist(professional(area="Nutrição", areas=["Psicoterapia", "Nutrição"])) is True
    assert is_psychologist(professional(area="Psicoterapia", areas=["Nutrição"])) is False


def test_psychologist_by_legacy_area_with_aliases_and_commas():
    assert is_psychologist(professional(area="Psicoterapia, Psiquiatria")) is True
    assert is_psychologist(professional(area="Psicanálise")) is True
    assert is_psychologist(professional(area="psicoterapia tcc")) is True
    assert is_psychologist(professional(area="Nutrição")) is False


def test_pending_review_is_never_eligible():
    assert PENDING_REVIEW == "PENDING_REVIEW"
    assert is_eligible_for_immediate(professional(register_type="PENDING_REVIEW")) is False
    assert is_eligible_for_immediate(professional()) is True
    assert is_eligible_for_immediate(professional(area="Nutrição")) is False
