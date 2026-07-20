"""Repository for temporary patient registration persistence."""

import json
import logging
from datetime import datetime
from typing import Any, cast

import redis.asyncio as redis

from app.domain.message import Message
from app.domain.patient_stage import PatientStageContext

logger = logging.getLogger(__name__)


class PatientStageRepository:
    """Encapsulates Redis operations for patient registration drafts."""

    redis_client: redis.Redis  # type: ignore[type-arg]

    TTL_SECONDS = 90 * 60

    def __init__(self, redis_client: redis.Redis) -> None:  # type: ignore[type-arg]
        self.redis_client = redis_client

    def _draft_key(self, message: Message) -> str:
        return f"patient_stage:{message.channel}:{message.user_id}"

    async def get_context(
        self,
        message: Message,
    ) -> PatientStageContext | None:
        result = await self.redis_client.get(self._draft_key(message))
        context_json = cast(str | None, result)

        if not context_json:
            return None

        try:
            context_dict = json.loads(context_json)
            return PatientStageContext(**context_dict)
        except json.JSONDecodeError:
            logger.error(
                "Failed to decode patient stage: %s",
                context_json,
            )
            return None
        except TypeError:
            logger.error(
                "Invalid patient stage payload: %s",
                context_json,
            )
            return None

    async def create_context(
        self,
        message: Message,
    ) -> PatientStageContext:
        context = PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
        )

        await self.save_context(message, context)

        return context

    async def get_or_create_context(
        self,
        message: Message,
    ) -> PatientStageContext:
        context = await self.get_context(message)

        if context is not None:
            return context

        return await self.create_context(message)

    async def save_context(
        self,
        message: Message,
        context: PatientStageContext,
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
                "Failed to save patient stage for user_id %s",
                message.user_id,
            )
            raise

    async def update_context(
        self,
        message: Message,
        data: dict[str, Any],
    ) -> PatientStageContext:
        context = await self.get_or_create_context(message)

        updated_context = context.model_copy(update=data)

        await self.save_context(message, updated_context)

        return updated_context
