"""Typed matching contracts shared by the chatbot, Lambda and simulations."""
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal

from app.domain.enum.channels import Channel


@dataclass(frozen=True)
class PatientReference:
    patient_id: int


@dataclass(frozen=True)
class PatientRegistration:
    name: str
    phone_number: str
    birth_date: date
    area: str
    channel: Channel = Channel.WHATSAPP
    psychotherapy_approach: str | None = None
    professional_profile: str | None = None


PatientInput = PatientReference | PatientRegistration


@dataclass(frozen=True)
class Patient:
    id: int
    area: str | None
    psychotherapy_approach: str | None = None
    professional_profile: str | None = None


@dataclass
class Candidate:
    id: int
    area: str
    starts_at: datetime
    deadline_at: datetime
    promised_patients: int
    used: int
    professional_id: int = 0
    cancelled_at: datetime | None = None
    type: str = "REGULAR"
    approach: str | None = None
    gender: str | None = None
    minority_group: str | None = None


@dataclass(frozen=True)
class ScoreBreakdown:
    phase: str
    evaluated_at: str
    area: str
    deadline_at: str
    preferences_enabled: bool = False
    tie_break: str = "deadline,cycle_id"


@dataclass(frozen=True)
class Score:
    compatibility: float
    urgency: float
    final: float
    breakdown: ScoreBreakdown


@dataclass(frozen=True)
class MatchResult:
    patient_id: int
    status: Literal["matched", "no_capacity", "patient_not_found"]
    slot_id: int | None = None
    cycle_id: int | None = None

    def as_payload(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}
