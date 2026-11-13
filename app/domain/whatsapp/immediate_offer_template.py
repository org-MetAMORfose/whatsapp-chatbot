"""Values expected by the approved `acolhimento_oferta` template (quick-reply button "Aceitar").

Body registered in Meta: "Novo acolhimento imediato: {{1}} precisa de uma sessão de {{2}} minutos agora
(R$ {{3}}). Toque em Aceitar nos próximos 5 minutos para ficar com o atendimento."
"""

from dataclasses import dataclass
from typing import ClassVar

from app.domain.sheets.professional import normalize_phone
from app.domain.whatsapp.matching_patient_template import whatsapp_phone
from app.services.pix.gateway import format_reais


def amount_text(cents: int) -> str:
    """Template parameter without the currency sign: 6000 -> "60,00"."""
    return format_reais(cents).removeprefix("R$ ")


@dataclass(frozen=True)
class ImmediateOfferTemplate:
    professional_phone: str
    patient_first_name: str
    duration_minutes: int
    amount_text: str

    name: ClassVar[str] = "acolhimento_oferta"
    language: ClassVar[str] = "pt_BR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "professional_phone", whatsapp_phone(normalize_phone(self.professional_phone)))
        first_name = self.patient_first_name.strip()
        if not first_name:
            raise ValueError("Missing patient_first_name")
        object.__setattr__(self, "patient_first_name", first_name)
        if self.duration_minutes <= 0:
            raise ValueError("Invalid duration_minutes")
        if not self.amount_text.strip():
            raise ValueError("Missing amount_text")

    @property
    def body_parameters(self) -> tuple[str, str, str]:
        return self.patient_first_name, str(self.duration_minutes), self.amount_text
