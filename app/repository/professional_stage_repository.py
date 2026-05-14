"""Repository for temporary professional registration persistence."""

import json
import logging
from datetime import datetime
from typing import Any, cast

import redis.asyncio as redis

from app.domain.message import Message
from app.domain.professional_stage import ProfessionalStageContext

logger = logging.getLogger(__name__)


class ProfessionalStageRepository:
    """Encapsulates Redis operations for professional registration drafts."""

    redis_client: redis.Redis  # type: ignore[type-arg]

    TTL_SECONDS = 90 * 60

    def __init__(self, redis_client: redis.Redis) -> None:  # type: ignore[type-arg]
        self.redis_client = redis_client

    def _draft_key(self, message: Message) -> str:
        return f"professional_stage:{message.channel}:{message.user_id}"

    async def get_context(
        self,
        message: Message,
    ) -> ProfessionalStageContext | None:
        result = await self.redis_client.get(self._draft_key(message))
        context_json = cast(str | None, result)

        if not context_json:
            return None

        try:
            context_dict = json.loads(context_json)
            return ProfessionalStageContext(**context_dict)
        except json.JSONDecodeError:
            logger.error(
                "Failed to decode professional stage: %s",
                context_json,
            )
            return None
        except TypeError:
            logger.error(
                "Invalid professional stage payload: %s",
                context_json,
            )
            return None

    async def create_context(
        self,
        message: Message,
    ) -> ProfessionalStageContext:
        context = ProfessionalStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
        )

        await self.save_context(message, context)

        return context

    async def get_or_create_context(
        self,
        message: Message,
    ) -> ProfessionalStageContext:
        context = await self.get_context(message)

        if context is not None:
            return context

        return await self.create_context(message)

    async def save_context(
        self,
        message: Message,
        context: ProfessionalStageContext,
    ) -> None:
        context.updated_at = datetime.utcnow()
        context_json = context.model_dump_json()

        try:
            await self.redis_client.set(
                self._draft_key(message),
                context_json,
                ex=self.TTL_SECONDS,
            )
        except redis.RedisError:
            logger.exception(
                "Failed to save professional stage for user_id %s",
                message.user_id,
            )
            raise

    async def update_context(
        self,
        message: Message,
        data: dict[str, Any],
    ) -> ProfessionalStageContext:
        context = await self.get_or_create_context(message)

        updated_context = context.model_copy(update=data)

        await self.save_context(message, updated_context)

        return updated_context