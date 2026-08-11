"""Executes configured agent actions for the chat flow."""

import asyncio
import logging
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Final

from pydantic import ValidationError

from app.agent.chat_flow import Node
from app.domain.db.patient_model import PatientModel
from app.domain.enum.chat_state import ChatState
from app.domain.message import Message
from app.domain.patient_stage import PatientStageContext
from app.domain.sheets import PatientSheet, ProfessionalSheet
from app.repository.patient_repository import PatientRepository
from app.repository.patient_stage_repository import PatientStageRepository
from app.repository.person_repository import PersonRepository
from app.repository.professional_repository import ProfessionalRepository
from app.repository.professional_stage_repository import (
    ProfessionalStageRepository,
)
from app.services.google_sheets_service import (
    GoogleSheetsService,
    GoogleSheetsServiceError,
)


@dataclass
class ActionResult:
    """Output emitted by an action, optionally overriding the next flow node."""

    output: str = ""
    next_node: str | None = None


ActionOutput = str | ActionResult
Action = Callable[[Message], Awaitable[ActionOutput]]

logger = logging.getLogger(__name__)

PATIENT_PRICE_RANGES: Final[frozenset[str]] = frozenset(
    {
        "ate r$150",
        "ate r$300",
        "ate r$600",
    }
)


class ActionExecutor:
    """Executes actions declared in the flow file."""

    def __init__(
        self,
        professional_stage_repository: ProfessionalStageRepository,
        professional_repository: ProfessionalRepository,
        person_repository: PersonRepository,
        patient_repository: PatientRepository,
        patient_stage_repository: PatientStageRepository,
        google_sheets_service: GoogleSheetsService,
    ) -> None:
        self.professional_stage_repository = professional_stage_repository
        self.professional_repository = professional_repository
        self.person_repository = person_repository
        self.patient_repository = patient_repository
        self.patient_stage_repository = patient_stage_repository
        self.google_sheets_service = google_sheets_service

        self.actions: Final[dict[str, Action]] = {
            "redis_create_professional_stage": (
                self.redis_create_professional_stage
            ),
            "redis_update_professional_name": partial(
                self.redis_update_professional,
                field="name",
            ),
            "redis_update_professional_email": partial(
                self.redis_update_professional,
                field="email",
            ),
            "redis_update_professional_area": partial(
                self.redis_update_professional,
                field="area",
            ),
            "redis_update_professional_approach": partial(
                self.redis_update_professional,
                field="approach",
            ),
            "redis_update_professional_gender": partial(
                self.redis_update_professional,
                field="gender",
            ),
            "redis_update_professional_minority_group": partial(
                self.redis_update_professional,
                field="minority_group",
            ),
            "redis_update_professional_qualification": partial(
                self.redis_update_professional,
                field="qualification",
            ),
            "redis_update_professional_video_tool": partial(
                self.redis_update_professional,
                field="video_tool",
            ),
            "redis_update_professional_council_registration": partial(
                self.redis_update_professional,
                field="council_registration",
            ),
            "redis_update_professional_council_registration_document": (
                self.redis_update_professional_council_registration_document
            ),
            "redis_get_professional_stage_summary": (
                self.redis_get_professional_stage_summary
            ),
            "postgres_register_professional_application": (
                self.postgres_register_professional_application
            ),
            "postgres_set_professional_registration_state": partial(
                self.postgres_set_chat_state,
                chat_state=ChatState.PROFESSIONAL_REGISTRATION,
            ),
            "postgres_set_payment_renewal_state": partial(
                self.postgres_set_chat_state,
                chat_state=ChatState.PAYMENT_RENEWAL,
            ),
            "postgres_set_question_state": partial(
                self.postgres_set_chat_state,
                chat_state=ChatState.QUESTION,
            ),
            "postgres_set_feedback_state": partial(
                self.postgres_set_chat_state,
                chat_state=ChatState.FEEDBACK,
            ),
            "postgres_set_professional_support_state": (
                self.postgres_set_professional_support_state
            ),
            "postgres_set_new_patient_state": self.postgres_set_new_patient_state,
            "postgres_set_returning_patient_state": (
                self.postgres_set_returning_patient_state
            ),
            "postgres_route_patient_registration": (
                self.postgres_route_patient_registration
            ),
            "postgres_register_new_patient_request": (
                self.postgres_register_new_patient_request
            ),
            "postgres_register_returning_patient_from_last_request": (
                self.postgres_register_returning_patient_from_last_request
            ),
            "postgres_route_patient_preference_update": (
                self.postgres_route_patient_preference_update
            ),
            "redis_update_patient_name": partial(
                self.redis_update_patient,
                field="name",
            ),
            "redis_update_patient_area": partial(
                self.redis_update_patient,
                field="area",
            ),
            "redis_update_patient_psychotherapy_approach": partial(
                self.redis_update_patient,
                field="psychotherapy_approach",
            ),
            "redis_update_patient_professional_profile": partial(
                self.redis_update_patient,
                field="professional_profile",
            ),
            "redis_update_patient_price_range": partial(
                self.redis_update_patient,
                field="price_range",
            ),
            "redis_get_patient_stage_summary": self.redis_get_patient_stage_summary,
            "sheets_register_patient": self.sheets_register_patient,
            "sheets_register_professional": self.sheets_register_professional,
        }

    async def run(self, node: Node, message: Message) -> ActionResult:
        """Execute actions by name."""
        result = ActionResult()

        for name in node.actions:
            action = self.actions.get(name)

            logger.debug(
                f"Executing action: {name} "
                f"for message {message.message_id}"
            )

            if action is None:
                raise ValueError(f"Unknown action: {name}")

            action_result = await action(message)
            if isinstance(action_result, ActionResult):
                result.output += action_result.output
                if action_result.next_node is not None:
                    result.next_node = action_result.next_node
            else:
                result.output += action_result

        return result

    async def redis_create_professional_stage(
        self,
        message: Message,
    ) -> str:
        """Create temporary professional registration context."""
        await self.professional_stage_repository.get_or_create_context(
            message
        )
        return ""

    async def redis_update_professional(
        self,
        message: Message,
        *,
        field: str,
    ) -> str:
        """Store a professional text field."""
        await self.professional_stage_repository.update_context(
            message,
            {field: message.content},
        )
        return ""

    async def redis_update_professional_council_registration_document(
        self,
        message: Message,
    ) -> str:
        """Store professional document media id."""
        media = message.image or message.document

        if media is None:
            if message.content and message.content.strip().lower() == "sem registro":
                await self.professional_stage_repository.update_context(
                    message,
                    {
                        "council_registration": "Sem registro",
                    },
                )

            return ""

        await self.professional_stage_repository.update_context(
            message,
            {
                "council_registration": "Documento enviado",
                "council_registration_document": media,
            },
        )

        return ""

    async def redis_get_professional_stage_summary(
        self,
        message: Message,
    ) -> str:
        """Return a summary of the professional registration context."""
        context = await self.professional_stage_repository.get_context(
            message
        )

        if context is None:
            return "Não encontrei os dados preenchidos até agora.\n"

        def format_value(
            value: str | None,
            max_length: int = 100,
        ) -> str:
            if value is None or value.strip() == "":
                return "Não informado"

            value = value.strip()

            if len(value) > max_length:
                return f"{value[:max_length]}..."

            return value

        return (
            "Resumo dos dados informados:\n"
            f"- Nome: {format_value(context.name, 50)}\n"
            f"- E-mail: {format_value(context.email, 80)}\n"
            f"- Área de atuação: {format_value(context.area, 50)}\n"
            f"- Abordagem: {format_value(context.approach, 50)}\n"
            f"- Gênero: {format_value(context.gender, 30)}\n"
            f"- Identificação: {format_value(context.minority_group, 50)}\n"
            f"- Qualificação/currículo: "
            f"{format_value(context.qualification, 200)}\n"
            f"- Ferramenta online: {format_value(context.video_tool, 50)}\n"
            f"- Registro profissional: "
            f"{format_value(context.council_registration, 50)}\n"
        )

    async def postgres_register_professional_application(
        self,
        message: Message,
    ) -> str:
        """Register professional application in PostgreSQL after Pix receipt."""
        context = await self.professional_stage_repository.get_context(message)
        if context is None:
            logger.error(
                "Professional stage not found for user_id %s",
                message.user_id,
            )
            return ""

        person = self.person_repository.get_by_phone_number_and_channel(
            message.user_id,
            message.channel,
        )
        if person is None:
            logger.error(
                "Person not found while registering professional user_id %s",
                message.user_id,
            )
            return ""

        if context.name:
            person.name = context.name
            self.person_repository.update(person)

        self.professional_repository.create_application(
            person_id=person.id,
            area=context.area or "Não informado",
            professional_register=f"PENDING-{person.id}",
            register_type="PENDING_REVIEW",
            approach=context.approach,
            background=context.qualification,
            video_platform=context.video_tool,
            email=context.email,
            created_at=message.created_at,
        )
        return ""

    async def postgres_set_chat_state(
        self,
        message: Message,
        *,
        chat_state: ChatState,
    ) -> str:
        """Set an administrative chat state according to its priority."""
        self.person_repository.update_chat_state_by_contact(
            phone_number=message.user_id,
            channel=message.channel,
            chat_state=chat_state,
        )
        return ""

    async def postgres_set_professional_support_state(
        self,
        message: Message,
    ) -> str:
        """Flag requests made through the professional support option."""
        content = (message.content or "").strip().lower()
        if content == "outros assuntos":
            await self.postgres_set_chat_state(
                message,
                chat_state=ChatState.PROFESSIONAL_SUPPORT,
            )
        return ""

    async def postgres_set_new_patient_state(
        self,
        message: Message,
    ) -> str:
        """Flag a patient who requested a session."""
        content = (message.content or "").strip().lower()
        if content == "quero sessão":
            await self.postgres_set_chat_state(
                message,
                chat_state=ChatState.NEW_PATIENT,
            )
        return ""

    async def postgres_set_returning_patient_state(
        self,
        message: Message,
    ) -> str:
        """Flag a patient who has already completed a normal registration."""
        await self.postgres_set_chat_state(
            message,
            chat_state=ChatState.RETURNING_PATIENT,
        )
        return ""

    async def postgres_route_patient_registration(
        self,
        message: Message,
    ) -> ActionResult:
        """Route a normal appointment to the first-time or returning flow."""
        if (message.content or "").strip().lower() != "atendimento normal":
            return ActionResult()

        person = self.person_repository.get_by_phone_number_and_channel(
            message.user_id,
            message.channel,
        )
        if person is None:
            logger.error(
                "Person not found while routing patient user_id %s",
                message.user_id,
            )
            return ActionResult()

        if not self.patient_repository.exists_by_person_id(person.id):
            await self.patient_stage_repository.create_context(message)
            return ActionResult(next_node="paciente_nome")

        latest_patient = self.patient_repository.get_latest_by_person_id(person.id)
        if latest_patient is None:
            logger.error(
                "Patient request disappeared while routing person_id %s",
                person.id,
            )
            return ActionResult(next_node="paciente_nome")

        await self.patient_stage_repository.create_context(message)
        context = await self.patient_stage_repository.update_context(
            message,
            {
                "name": person.name,
                "area": latest_patient.area,
                "psychotherapy_approach": latest_patient.psychotherapy_approach,
                "professional_profile": latest_patient.professional_profile,
                "price_range": latest_patient.price_range,
                "is_returning": True,
            },
        )
        return ActionResult(
            output=self._format_patient_summary(context, message.user_id),
            next_node="paciente_retorno_resumo",
        )

    async def postgres_register_new_patient_request(
        self,
        message: Message,
    ) -> str:
        """Persist the first normal patient registration."""
        if not self._is_patient_price_range(message):
            return ""
        await self._register_patient_request(message, is_returning=False)
        return ""

    async def postgres_register_returning_patient_from_last_request(
        self,
        message: Message,
    ) -> str:
        """Persist a copy of the latest preferences when they are kept."""
        if self._normalize_content(message.content) == "manter":
            await self._register_patient_request(message, is_returning=True)
        return ""

    async def postgres_route_patient_preference_update(
        self,
        message: Message,
    ) -> ActionResult:
        """Show only preference fields that apply to the patient's current area."""
        if self._normalize_content(message.content) != "atualizar":
            return ActionResult()

        context = await self.patient_stage_repository.get_context(message)
        if context is None:
            logger.error(
                "Patient stage not found while updating preferences for user_id %s",
                message.user_id,
            )
            return ActionResult()

        next_node = (
            "paciente_retorno_campos_psicoterapia"
            if self._normalize_content(context.area) == "psicoterapia"
            else "paciente_retorno_campos_geral"
        )
        return ActionResult(next_node=next_node)

    async def _register_patient_request(
        self,
        message: Message,
        *,
        is_returning: bool,
    ) -> None:
        context = await self.patient_stage_repository.get_context(message)
        if context is None:
            logger.error(
                "Patient stage not found while registering user_id %s",
                message.user_id,
            )
            return

        if context.is_returning != is_returning:
            logger.error(
                "Patient stage type does not match registration for user_id %s",
                message.user_id,
            )
            return

        person = self.person_repository.get_by_phone_number_and_channel(
            message.user_id,
            message.channel,
        )
        if person is None:
            logger.error(
                "Person not found while registering patient user_id %s",
                message.user_id,
            )
            return

        if context.name and context.name != person.name:
            person.name = context.name
            self.person_repository.update(person)

        self.patient_repository.create(
            PatientModel(
                person_id=person.id,
                area=context.area,
                psychotherapy_approach=context.psychotherapy_approach,
                professional_profile=context.professional_profile,
                price_range=context.price_range,
                created_at=message.created_at or datetime.utcnow(),
            )
        )
        await self.postgres_set_chat_state(
            message,
            chat_state=(
                ChatState.RETURNING_PATIENT
                if is_returning
                else ChatState.NEW_PATIENT
            ),
        )

    async def redis_update_patient(
        self,
        message: Message,
        *,
        field: str,
    ) -> str:
        """Store a patient text field."""
        data = {field: message.content}
        if field == "area" and self._normalize_content(message.content) != "psicoterapia":
            data["psychotherapy_approach"] = None
        await self.patient_stage_repository.update_context(message, data)
        return ""

    async def redis_get_patient_stage_summary(
        self,
        message: Message,
    ) -> str:
        """Return a summary of the patient preferences stored in Redis."""
        context = await self.patient_stage_repository.get_context(message)
        if context is None:
            return "Não encontrei os dados preenchidos até agora.\n"
        return self._format_patient_summary(context, message.user_id)

    @staticmethod
    def _format_patient_summary(
        context: PatientStageContext,
        phone_number: str,
    ) -> str:
        def format_value(value: str | None) -> str:
            if value is None or value.strip() == "":
                return "Não informado"
            return value.strip()

        summary = (
            "Resumo dos seus dados atuais:\n"
            f"- Nome: {format_value(context.name)}\n"
            f"- Telefone: {phone_number}\n"
            f"- Área: {format_value(context.area)}\n"
        )
        if ActionExecutor._normalize_content(context.area) == "psicoterapia":
            summary += (
                "- Abordagem em psicoterapia: "
                f"{format_value(context.psychotherapy_approach)}\n"
            )

        return summary + (
            f"- Perfil profissional: {format_value(context.professional_profile)}\n"
            f"- Faixa de valor: {format_value(context.price_range)}\n\n"
        )

    @staticmethod
    def _normalize_content(value: str | None) -> str:
        content = unicodedata.normalize(
            "NFKD",
            (value or "").strip().lower(),
        )
        return "".join(
            character
            for character in content
            if not unicodedata.combining(character)
        )

    @classmethod
    def _is_patient_price_range(cls, message: Message) -> bool:
        return cls._normalize_content(message.content) in PATIENT_PRICE_RANGES

    async def sheets_register_patient(
        self,
        message: Message,
    ) -> str:
        """Write the patient's data to the patients Google Sheet."""
        context = await self.patient_stage_repository.get_context(message)
        if context is None:
            logger.error(
                "Patient stage not found for user_id %s",
                message.user_id,
            )
            return ""

        if context.is_returning:
            return ""

        if not self._is_patient_price_range(message):
            return ""

        try:
            patient = PatientSheet(
                name=context.name or "",
                phone=message.user_id,
                area=context.area or "",
            )
            await asyncio.to_thread(
                self.google_sheets_service.register_patient, patient
            )
        except (GoogleSheetsServiceError, ValidationError):
            logger.exception(
                "Failed to register patient %s in Google Sheets",
                message.user_id,
            )

        return ""

    async def sheets_register_professional(
        self,
        message: Message,
    ) -> str:
        """Write the professional's data to the professionals Google Sheet."""
        context = await self.professional_stage_repository.get_context(message)
        if context is None:
            logger.error(
                "Professional stage not found for user_id %s",
                message.user_id,
            )
            return ""

        try:
            professional = ProfessionalSheet(
                name=context.name or "",
                area=context.area or "",
                phone=message.user_id,
                active=False,
            )
            await asyncio.to_thread(
                self.google_sheets_service.register_professional, professional
            )
        except (GoogleSheetsServiceError, ValidationError):
            logger.exception(
                "Failed to register professional %s in Google Sheets",
                message.user_id,
            )

        return ""
