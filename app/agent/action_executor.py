"""Executes configured agent actions for the chat flow."""

import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final

from app.agent.chat_flow import Node
from app.domain.message import Message
from app.repository.professional_repository import ProfessionalRepository
from app.repository.professional_stage_repository import (
    ProfessionalStageRepository,
)

Action = Callable[[Message], Awaitable[str]]

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes actions declared in the flow file."""

    def __init__(
        self,
        professional_stage_repository: ProfessionalStageRepository,
        professional_repository: ProfessionalRepository,
    ) -> None:
        self.professional_stage_repository = professional_stage_repository
        self.professional_repository = professional_repository

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
        }

    async def run(self, node: Node, message: Message) -> str:
        """Execute actions by name."""
        result = ""

        for name in node.actions:
            action = self.actions.get(name)

            logger.debug(
                f"Executing action: {name} "
                f"for message {message.message_id}"
            )

            if action is None:
                raise ValueError(f"Unknown action: {name}")

            result += await action(message)

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
        """Register professional application in PostgreSQL."""

        return ""
