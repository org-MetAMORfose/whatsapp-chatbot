"""Management endpoints for immediate care: professional availability and the request list for the panel."""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.controllers.auth import ApiKeyHeader, require_chatbot_api_key
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.professional_repository import ProfessionalRepository


class AvailabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def serialize_request(request: ImmediateRequestModel) -> dict[str, object]:
    patient = request.patient
    professional = request.professional
    return {
        "id": request.id,
        "status": request.status,
        "duration_minutes": request.duration_minutes,
        "amount_cents": request.amount_cents,
        "patient_name": patient.name if patient is not None else None,
        "patient_phone": patient.phone_number if patient is not None else None,
        "professional_name": professional.name if professional is not None else None,
        "professional_phone": professional.phone_number if professional is not None else None,
        "pix_txid": request.pix_txid,
        "pix_refund_id": request.pix_refund_id,
        "room_url": request.room_url,
        "paid_at": _iso(request.paid_at),
        "accepted_at": _iso(request.accepted_at),
        "refunded_at": _iso(request.refunded_at),
        "expires_at": _iso(request.expires_at),
        "created_at": _iso(request.created_at),
    }


class ImmediateCareController:
    def __init__(self, professionals: ProfessionalRepository, requests: ImmediateRequestRepository) -> None:
        self._professionals = professionals
        self._requests = requests
        self.router = APIRouter()
        self.router.add_api_route("/immediate/professionals/{professional_id}/availability", self.set_availability, methods=["PATCH"])
        self.router.add_api_route("/immediate/requests", self.list_requests, methods=["GET"])

    def set_availability(self, professional_id: int, body: AvailabilityBody, chatbot_api_key: ApiKeyHeader = None) -> dict[str, object]:
        require_chatbot_api_key(chatbot_api_key)
        professional = self._professionals.get_by_id(professional_id)
        if professional is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        updated = self._professionals.set_available_for_immediate(professional.person_id, body.available, now=datetime.now(UTC))
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profissional não encontrado.")
        return {"professional_id": updated.id, "available_for_immediate": updated.available_for_immediate}

    def list_requests(
        self,
        chatbot_api_key: ApiKeyHeader = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[dict[str, object]]:
        require_chatbot_api_key(chatbot_api_key)
        return [serialize_request(request) for request in self._requests.list_recent(limit=limit)]
