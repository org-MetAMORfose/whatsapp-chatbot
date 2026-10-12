"""Transactional patient and professional registrations used by the HTTP API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.domain.db.patient_model import PatientModel
from app.domain.enum.channels import Channel
from app.domain.matching.profile import patient_request, professional_profile
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
    psychotherapy_approach: str | None = None
    professional_profile: str | None = None
    psychotherapy_specialties: list[str] | None = None
    preferred_gender: str | None = None
    preferred_race: str | None = None
    prefers_lgbtqiapn_plus: bool | None = None


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
    areas: list[str] | None = None
    approaches: list[str] | None = None
    psychotherapy_specialties: list[str] | None = None
    race: str | None = None
    lgbtqiapn_plus: bool | None = None


@dataclass(frozen=True)
class ProfessionalUpdateData:
    name: str
    phone: str
    email: str
    area: str
    birth_date: date | None = None
    gender: str | None = None
    minority_group: str | None = None
    background: str | None = None
    video_platform: str | None = None
    areas: list[str] | None = None
    approaches: list[str] | None = None
    psychotherapy_specialties: list[str] | None = None
    race: str | None = None
    lgbtqiapn_plus: bool | None = None
    provided_fields: frozenset[str] = frozenset()


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
                if person.name != data.name or (data.birth_date is not None and person.birth_date != data.birth_date):
                    person.name = data.name
                    if data.birth_date is not None:
                        person.birth_date = data.birth_date
                    person = self._people.update(person)

                patient = self._patients.create(
                    PatientModel(
                        person_id=person.id,
                        area=data.area,
                        psychotherapy_approach=data.psychotherapy_approach,
                        professional_profile=data.professional_profile,
                        matching_request=patient_request(
                            selected_area=data.area, selected_approach=data.psychotherapy_approach,
                            professional_profile=data.professional_profile, focus=data.psychotherapy_specialties,
                            preferred_gender=data.preferred_gender, preferred_race=data.preferred_race,
                            prefers_lgbtqiapn_plus=data.prefers_lgbtqiapn_plus,
                        ),
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

    def update_professional(
        self,
        professional_id: int,
        data: ProfessionalUpdateData,
    ) -> RegisteredProfessional | None:
        with transaction(self._session_factory):
            professional = self._professionals.get_by_id(professional_id)
            if professional is None:
                return None

            person = professional.person
            person.name = data.name
            person.phone_number = data.phone
            person.birth_date = data.birth_date
            self._people.update(person)

            professional.area = data.area
            professional.email = data.email
            track_fields = bool(data.provided_fields)
            if not track_fields or "gender" in data.provided_fields:
                professional.gender = data.gender
            professional.minority_group = data.minority_group
            professional.background = data.background
            professional.video_platform = data.video_platform
            previous = professional.matching_profile or {}
            previous_psychotherapy = previous.get("psychotherapy") or {}
            previous_identity = previous.get("profile") or {}
            areas_provided = "areas" in data.provided_fields or (
                not track_fields and data.areas is not None
            )
            approaches_provided = "approaches" in data.provided_fields or (
                not track_fields and data.approaches is not None
            )
            specialties_provided = "psychotherapy_specialties" in data.provided_fields or (
                not track_fields and data.psychotherapy_specialties is not None
            )
            race_provided = "race" in data.provided_fields or (
                not track_fields and data.race is not None
            )
            lgbtqiapn_plus_provided = "lgbtqiapn_plus" in data.provided_fields or (
                not track_fields and data.lgbtqiapn_plus is not None
            )
            professional.matching_profile = professional_profile(
                areas=[data.area, *((data.areas or []) if areas_provided
                                     else (previous.get("areas", []) if data.area in previous.get("areas", []) else []))],
                approaches=data.approaches if approaches_provided
                    else previous_psychotherapy.get("approaches", []),
                focus=data.psychotherapy_specialties if specialties_provided
                    else previous_psychotherapy.get("specialties", []),
                gender=professional.gender, minority_group=data.minority_group,
                race=data.race if race_provided else previous_identity.get("race"),
                lgbtqiapn_plus=data.lgbtqiapn_plus if lgbtqiapn_plus_provided
                    else previous_identity.get("lgbtqiapn_plus"),
            )
            professional = self._professionals.update(professional)
            return RegisteredProfessional(professional.id, professional.person_id)

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
            if person.name != data.name or (data.birth_date is not None and person.birth_date != data.birth_date):
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
                matching_profile=professional_profile(
                    areas=[data.area, *(data.areas or [])],
                    approaches=data.approaches or ([data.approach] if data.approach else []),
                    focus=data.psychotherapy_specialties, gender=data.gender,
                    minority_group=data.minority_group, race=data.race,
                    lgbtqiapn_plus=data.lgbtqiapn_plus,
                ),
                created_at=datetime.now(UTC),
            )
            return RegisteredProfessional(professional.id, person.id)
