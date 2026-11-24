"""Values expected by the approved `acolhimento_solicitacao` template (Utility, quick-reply button "Aceitar").

Body registered in Meta: "Você está como DISPONÍVEL no acolhimento imediato e chegou uma solicitação: {{1}}, sessão de
{{2}} minutos, R$ {{3}}. Para atender, toque em Aceitar em até 5 minutos; quem aceitar primeiro fica com o atendimento.
Para parar de receber, envie INDISPONÍVEL."

The first version (`acolhimento_oferta`) was approved as Marketing, which costs more and can be held back by WhatsApp;
this wording, tied to the professional's DISPONÍVEL status, was approved as Utility.
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

    name: ClassVar[str] = "acolhimento_solicitacao"
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
