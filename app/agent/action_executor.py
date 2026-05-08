"""Executes configured agent actions for the chat flow."""

import logging
from collections.abc import Awaitable, Callable
from typing import Final

from app.domain.message import Message
from app.repository.professional_stage_repository import ProfessionalStageRepository

Action = Callable[[Message], Awaitable[None]]

logger = logging.getLogger(__name__)

class ActionExecutor:
    """Executes actions declared in the flow file."""

    def __init__(self, professional_stage_repository: ProfessionalStageRepository) -> None:
        self.professional_stage_repository = professional_stage_repository

        self.actions: Final[dict[str, Action]] = {
            "redis_create_professional_stage": self.redis_create_professional_stage,
            "redis_update_professional_qualification": (
                self.redis_update_professional_qualification
            ),
            "redis_update_professional_video_tool": self.redis_update_professional_video_tool,
            "redis_update_professional_council_registration": (
                self.redis_update_professional_council_registration
            ),
        }

    async def run(self, action_names: list[str], message: Message) -> None:
        """Execute actions by name."""
        for name in action_names:
            action = self.actions.get(name)
            logger.debug(f"Executing action: {name} for message {message.message_id}")

            if action is None:
                raise ValueError(f"Unknown action: {name}")

            await action(message)

    async def redis_create_professional_stage(self, message: Message) -> None:
        """Create temporary professional registration context."""
        await self.professional_stage_repository.get_or_create_context(message)

    async def redis_update_professional_qualification(self, message: Message) -> None:
        """Store professional qualification."""
        await self.professional_stage_repository.update_context(
            message,
            {"qualification": message.content},
        )

    async def redis_update_professional_video_tool(self, message: Message) -> None:
        """Store preferred video tool."""
        await self.professional_stage_repository.update_context(
            message,
            {"video_tool": message.content},
        )

    async def redis_update_professional_council_registration(self, message: Message) -> None:
        """Store council registration number."""
        await self.professional_stage_repository.update_context(
            message,
            {"council_registration": message.content},
        )