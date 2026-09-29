"""Values expected by the approved matching_professional template."""

from dataclasses import dataclass
from typing import ClassVar

from app.domain.whatsapp.matching_patient_template import whatsapp_phone


@dataclass(frozen=True)
class MatchingProfessionalTemplate:
    professional_phone: str
    patient_name: str
    patient_area: str
    patient_phone: str

    name: ClassVar[str] = "matching_professional"
    language: ClassVar[str] = "pt_BR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "professional_phone", whatsapp_phone(self.professional_phone))
        object.__setattr__(self, "patient_phone", whatsapp_phone(self.patient_phone))
        for field in ("patient_name", "patient_area"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing {field}")
            object.__setattr__(self, field, value.strip())

    @property
    def body_parameters(self) -> tuple[str, str, str]:
        return self.patient_name, self.patient_area, f"https://wa.me/{self.patient_phone}"
