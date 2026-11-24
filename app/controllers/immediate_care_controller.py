"""Management endpoints for immediate care, used by the panel: release a professional and switch availability.

The panel reads the request list straight from the database; no endpoint here returns patient data.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.controllers.auth import ApiKeyHeader, require_chatbot_api_key
from app.domain.db.professional_model import ProfessionalModel
from app.domain.immediate_eligibility import is_eligible_for_immediate, is_psychologist
from app.repository.sql.professional_repository import ProfessionalRepository


class AvailabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool


class ApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _state(professional: ProfessionalModel) -> dict[str, object]:
    return {
        "professional_id": professional.id,
        "immediate_approved_at": _iso(professional.immediate_approved_at),
        "available_for_immediate": professional.available_for_immediate,
    }


class ImmediateCareController:
    def __init__(self, professionals: ProfessionalRepository) -> None:
        self._professionals = professionals
        self.router = APIRouter()
        self.router.add_api_route("/immediate/professionals/{professional_id}/approval", self.set_approval, methods=["PATCH"])
        self.router.add_api_route("/immediate/professionals/{professional_id}/availability", self.set_availability, methods=["PATCH"])

    def set_approval(self, professional_id: int, body: ApprovalBody, chatbot_api_key: ApiKeyHeader = None) -> dict[str, object]:
        """The team releases a psychologist (after checking the CRP); withdrawing also switches availability off."""
        require_chatbot_api_key(chatbot_api_key)
        professional = self._professionals.get_by_id(professional_id)
        if professional is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        if body.approved and not is_psychologist(professional):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O acolhimento imediato é só para psicólogos.")
        updated = self._professionals.set_immediate_approval(professional_id, body.approved, now=datetime.now(UTC))
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        return _state(updated)

    def set_availability(self, professional_id: int, body: AvailabilityBody, chatbot_api_key: ApiKeyHeader = None) -> dict[str, object]:
        require_chatbot_api_key(chatbot_api_key)
        professional = self._professionals.get_by_id(professional_id)
        if professional is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        if body.available and not is_eligible_for_immediate(professional):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Só psicólogos liberados pela equipe podem ficar disponíveis para o acolhimento imediato.",
            )
        updated = self._professionals.set_available_for_immediate(professional.person_id, body.available, now=datetime.now(UTC))
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        return _state(updated)
