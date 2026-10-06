"""Send the acompanhamento_emparelhamento WhatsApp template."""

import logging
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.channels import Channel
from app.domain.sheets.professional import normalize_phone
from app.domain.whatsapp.matching_follow_up_template import MatchingFollowUpTemplate
from app.domain.whatsapp.matching_patient_template import whatsapp_phone
from app.domain.whatsapp.template_history import template_history_content
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository

logger = logging.getLogger(__name__)


class MatchingFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_phone: str
    professional_phone: str

    @field_validator("patient_phone", "professional_phone", mode="after")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return whatsapp_phone(normalize_phone(value))


class MatchingFollowUpResponse(BaseModel):
    status: str = "sent"
    message_id: str


class MatchingFollowUpController:
    def __init__(
        self,
        person_repository: PersonRepository,
        patient_repository: PatientRepository,
        professional_repository: ProfessionalRepository,
        whatsapp: WhatsAppAdapter,
    ) -> None:
        self._people = person_repository
        self._patients = patient_repository
        self._professionals = professional_repository
        self._whatsapp = whatsapp
        self.router = APIRouter()
        self.router.add_api_route(
            "/whatsapp/templates/acompanhamento_emparelhamento",
            self.send,
            methods=["POST"],
            response_model=MatchingFollowUpResponse,
        )

    async def send(self, body: MatchingFollowUpRequest) -> MatchingFollowUpResponse:
        patient_person = self._people.get_by_phone_number_and_channel(
            body.patient_phone,
            Channel.WHATSAPP,
        )
        if patient_person is None or not self._patients.exists_by_person_id(patient_person.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient was not found by phone number.",
            )

        professional_person = self._people.get_by_phone_number_and_channel(
            body.professional_phone,
            Channel.WHATSAPP,
        )
        professional = (
            self._professionals.get_by_person_id(professional_person.id)
            if professional_person is not None
            else None
        )
        if professional_person is None or professional is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Professional was not found by phone number.",
            )

        try:
            template = MatchingFollowUpTemplate(
                patient_phone=patient_person.phone_number,
                patient_name=patient_person.name or "",
                professional_name=professional_person.name or "",
                professional_area=professional.area,
                professional_phone=professional_person.phone_number,
            )
            message_id = await self._whatsapp.send_template(
                to=template.patient_phone,
                name=template.name,
                language=template.language,
                body_parameters=template.body_parameters,
            )
            self._people.create_message(
                MessageHistoryModel(
                    person_id=patient_person.id,
                    created_at=datetime.now(UTC).replace(tzinfo=None),
                    content=template_history_content(
                        template.name,
                        template.language,
                        template.body_parameters,
                    ),
                    media_path=None,
                    is_from_user=False,
                )
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except (httpx.HTTPError, RuntimeError) as exc:
            logger.exception("Failed to send matching follow-up template")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="WhatsApp rejected the matching follow-up template.",
            ) from exc

        return MatchingFollowUpResponse(message_id=message_id)
