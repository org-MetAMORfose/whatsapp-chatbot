import pytest

from app.domain.whatsapp.immediate_offer_template import ImmediateOfferTemplate, amount_text


def test_template_body_parameters() -> None:
    template = ImmediateOfferTemplate(professional_phone="+55 (11) 97777-6666", patient_first_name="Maria", duration_minutes=30, amount_text="60,00")
    assert template.name == "acolhimento_oferta"
    assert template.language == "pt_BR"
    assert template.professional_phone == "5511977776666"
    assert template.body_parameters == ("Maria", "30", "60,00")


def test_template_rejects_missing_name() -> None:
    with pytest.raises(ValueError):
        ImmediateOfferTemplate(professional_phone="5511977776666", patient_first_name="  ", duration_minutes=30, amount_text="60,00")


def test_amount_text_without_currency_sign() -> None:
    assert amount_text(6000) == "60,00"
    assert amount_text(9050) == "90,50"
