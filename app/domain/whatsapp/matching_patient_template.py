"""Values expected by the approved matching_paciente template; no template text."""
import re
from dataclasses import dataclass
from typing import ClassVar


def whatsapp_phone(value: str) -> str:
    """Normalize formatting, retaining the supplied international country code."""
    if not isinstance(value, str) or not re.fullmatch(r"\+?[0-9 ()-]+", value.strip()):
        raise ValueError("Missing or invalid WhatsApp phone number")
    digits = re.sub(r"[^0-9]", "", value)
    if not 8 <= len(digits) <= 15 or digits.startswith("0"):
        raise ValueError("WhatsApp phone must include its country code")
    return digits


@dataclass(frozen=True)
class MatchingPatientTemplate:
    patient_phone: str
    professional_name: str
    professional_area: str
    professional_phone: str

    name: ClassVar[str] = "matching_paciente"
    language: ClassVar[str] = "pt_BR"

    def __post_init__(self) -> None:
        object.__setattr__(self, "patient_phone", whatsapp_phone(self.patient_phone))
        object.__setattr__(self, "professional_phone", whatsapp_phone(self.professional_phone))
        for field in ("professional_name", "professional_area"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing {field}")
            object.__setattr__(self, field, value.strip())

    @property
    def body_parameters(self) -> tuple[str, str, str]:
        return self.professional_name, self.professional_area, f"https://wa.me/{self.professional_phone}"
