"""Executes configured agent actions for the chat flow."""

import logging
from collections.abc import Awaitable, Callable
from typing import Final

from app.agent.chat_flow import Node
from app.domain.message import Message
from app.repository.professional_stage_repository import ProfessionalStageRepository

Action = Callable[[Message], Awaitable[str]]

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes actions declared in the flow file."""

    def __init__(
        self,
        professional_stage_repository: ProfessionalStageRepository,
    ) -> None:
        self.professional_stage_repository = professional_stage_repository

        self.actions: Final[dict[str, Action]] = {
            "redis_create_professional_stage": self.redis_create_professional_stage,
            "redis_update_professional_qualification": (
                self.redis_update_professional_qualification
            ),
            "redis_update_professional_video_tool": (
                self.redis_update_professional_video_tool
            ),
            "redis_update_professional_council_registration": (
                self.redis_update_professional_council_registration
            ),
            "redis_get_professional_stage_context": (
                self.redis_get_professional_stage_context
            ),
        }

    async def run(self, node: Node, message: Message) -> str:
        """Execute actions by name."""
        action_names = node.actions
        result = ""

        for name in action_names:
            action = self.actions.get(name)
            logger.debug(
                f"Executing action: {name} for message {message.message_id}"
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

    async def redis_update_professional_qualification(
        self,
        message: Message,
    ) -> str:
        """Store professional qualification."""
        await self.professional_stage_repository.update_context(
            message,
            {"qualification": message.content},
        )

        return ""

    async def redis_update_professional_video_tool(
        self,
        message: Message,
    ) -> str:
        """Store preferred video tool."""
        await self.professional_stage_repository.update_context(
            message,
            {"video_tool": message.content},
        )

        return ""

    async def redis_update_professional_council_registration(
        self,
        message: Message,
    ) -> str:
        """Store council registration number."""
        await self.professional_stage_repository.update_context(
            message,
            {"council_registration": message.content},
        )

        return ""

    async def redis_get_professional_stage_context(
        self,
        message: Message,
    ) -> str:
        """Return professional registration context."""
        logger.info(
            f"Retrieving professional stage context for message {message.message_id}"
        )
        context = await self.professional_stage_repository.get_context(
            message
        )

        if context is None:
            return "Professional context not found.\n"

        return (
            f"Professional context:\n"
            f"- Qualification: {context.qualification}\n"
            f"- Video tool: {context.video_tool}\n"
            f"- Council registration: "
            f"{context.council_registration}\n"
        )