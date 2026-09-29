"""HTTP endpoints for patient and professional registrations."""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator
from sqlalchemy.exc import IntegrityError

from app.domain.sheets.professional import normalize_phone
from app.domain.whatsapp.matching_patient_template import whatsapp_phone
from app.services.registration_service import (
    PatientRegistrationData,
    ProfessionalRegistrationData,
    RegistrationService,
)


def _non_empty(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Value cannot be blank")
    return value


NonEmptyString = Annotated[str, AfterValidator(_non_empty)]


def _parse_birth_date(value: object) -> object:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        content = value.strip()
        for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(content, date_format).date()
            except ValueError:
                continue
    raise ValueError("birth_date must use DD/MM/YYYY or YYYY-MM-DD")


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyString
    phone: NonEmptyString
    area: NonEmptyString
    birth_date: date | None = None

    @field_validator("phone", mode="after")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return whatsapp_phone(normalize_phone(value))

    @field_validator("birth_date", mode="before")
    @classmethod
    def parse_birth_date(cls, value: object) -> object:
        return _parse_birth_date(value)

    @field_validator("birth_date", mode="after")
    @classmethod
    def reject_future_birth_date(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("birth_date cannot be in the future")
        return value


class PatientRegistrationRequest(RegistrationRequest):
    def to_service_data(self) -> PatientRegistrationData:
        return PatientRegistrationData(
            name=self.name,
            phone=self.phone,
            area=self.area,
            birth_date=self.birth_date,
        )


class ProfessionalRegistrationRequest(RegistrationRequest):
    email: NonEmptyString
    professional_register: str | None = None
    register_type: str | None = None
    approach: str | None = None
    gender: str | None = None
    minority_group: str | None = None
    background: str | None = None
    video_platform: str | None = None

    @field_validator(
        "professional_register",
        "register_type",
        "approach",
        "gender",
        "minority_group",
        "background",
        "video_platform",
        mode="before",
    )
    @classmethod
    def blank_optional_text_as_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    def to_service_data(self) -> ProfessionalRegistrationData:
        return ProfessionalRegistrationData(**self.model_dump())


class PatientRegistrationResponse(BaseModel):
    id: int
    person_id: int
    matching_status: str = "requested"


class PatientBatchRegistrationResponse(BaseModel):
    patients: list[PatientRegistrationResponse]


class ProfessionalRegistrationResponse(BaseModel):
    id: int
    person_id: int


class RegistrationController:
    def __init__(self, service: RegistrationService) -> None:
        self._service = service
        self.router = APIRouter()
        self.router.add_api_route(
            "/patients",
            self.register_patients,
            methods=["POST"],
            response_model=PatientBatchRegistrationResponse,
            status_code=status.HTTP_201_CREATED,
        )
        self.router.add_api_route(
            "/professionals",
            self.register_professional,
            methods=["POST"],
            response_model=ProfessionalRegistrationResponse,
            status_code=status.HTTP_201_CREATED,
        )

    def register_patients(
        self,
        body: PatientRegistrationRequest | list[PatientRegistrationRequest],
    ) -> PatientBatchRegistrationResponse:
        requests = body if isinstance(body, list) else [body]
        if not 1 <= len(requests) <= 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Send between 1 and 100 patients.",
            )
        try:
            registered = self._service.register_patients(
                [request.to_service_data() for request in requests]
            )
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A patient registration conflicts with an existing record.",
            ) from exc
        return PatientBatchRegistrationResponse(
            patients=[
                PatientRegistrationResponse(id=patient.id, person_id=patient.person_id)
                for patient in registered
            ]
        )

    def register_professional(
        self,
        body: ProfessionalRegistrationRequest,
    ) -> ProfessionalRegistrationResponse:
        try:
            professional = self._service.register_professional(body.to_service_data())
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The professional registration conflicts with an existing record.",
            ) from exc
        return ProfessionalRegistrationResponse(
            id=professional.id,
            person_id=professional.person_id,
        )
