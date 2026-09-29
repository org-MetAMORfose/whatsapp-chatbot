"""Transactional patient and professional registrations used by the HTTP API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.domain.db.patient_model import PatientModel
from app.domain.enum.channels import Channel
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.repository.sql.transaction import transaction


@dataclass(frozen=True)
class PatientRegistrationData:
    name: str
    phone: str
    area: str
    birth_date: date | None = None


@dataclass(frozen=True)
class RegisteredPatient:
    id: int
    person_id: int


@dataclass(frozen=True)
class ProfessionalRegistrationData:
    name: str
    phone: str
    email: str
    area: str
    birth_date: date | None = None
    professional_register: str | None = None
    register_type: str | None = None
    approach: str | None = None
    gender: str | None = None
    minority_group: str | None = None
    background: str | None = None
    video_platform: str | None = None


@dataclass(frozen=True)
class RegisteredProfessional:
    id: int
    person_id: int


class RegistrationService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        person_repository: PersonRepository,
        patient_repository: PatientRepository,
        professional_repository: ProfessionalRepository,
        outbox_repository: OutboxRepository,
    ) -> None:
        self._session_factory = session_factory
        self._people = person_repository
        self._patients = patient_repository
        self._professionals = professional_repository
        self._outbox = outbox_repository

    def register_patients(
        self,
        registrations: list[PatientRegistrationData],
    ) -> list[RegisteredPatient]:
        registered: list[RegisteredPatient] = []
        with transaction(self._session_factory):
            for data in registrations:
                person = self._people.get_or_create_person(
                    phone_number=data.phone,
                    channel=Channel.WHATSAPP,
                    name=data.name,
                )
                if person.name != data.name or (
                    data.birth_date is not None and person.birth_date != data.birth_date
                ):
                    person.name = data.name
                    if data.birth_date is not None:
                        person.birth_date = data.birth_date
                    person = self._people.update(person)

                patient = self._patients.create(
                    PatientModel(
                        person_id=person.id,
                        area=data.area,
                        created_at=datetime.now(UTC),
                    )
                )
                self._outbox.enqueue(
                    f"matching:patient:{patient.id}",
                    "matching.requested",
                    {"patient_id": patient.id, "source": "api"},
                )
                registered.append(RegisteredPatient(patient.id, person.id))
        return registered

    def register_professional(
        self,
        data: ProfessionalRegistrationData,
    ) -> RegisteredProfessional:
        with transaction(self._session_factory):
            person = self._people.get_or_create_person(
                phone_number=data.phone,
                channel=Channel.WHATSAPP,
                name=data.name,
            )
            if person.name != data.name or (
                data.birth_date is not None and person.birth_date != data.birth_date
            ):
                person.name = data.name
                if data.birth_date is not None:
                    person.birth_date = data.birth_date
                person = self._people.update(person)

            professional = self._professionals.create_application(
                person_id=person.id,
                area=data.area,
                professional_register=data.professional_register or f"PENDING-{person.id}",
                register_type=data.register_type or "PENDING_REVIEW",
                approach=data.approach,
                background=data.background,
                video_platform=data.video_platform,
                email=data.email,
                gender=data.gender,
                minority_group=data.minority_group,
                created_at=datetime.now(UTC),
            )
            return RegisteredProfessional(professional.id, person.id)
