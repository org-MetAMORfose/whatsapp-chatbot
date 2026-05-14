"""Repository for chat state persistence."""

import json
import logging
from typing import cast

import redis.asyncio as redis
from pydantic import ValidationError

from app.domain.chat import ChatContext
from app.domain.enum.channels import Channel
from app.domain.message import Message

logger = logging.getLogger(__name__)


class ChatRepository:
    """Encapsulates Redis operations for loading and saving chat context."""

    redis_client: redis.Redis  # type: ignore[type-arg]
    context_ttl_seconds: int

    def __init__(
        self,
        redis_client: redis.Redis,  # type: ignore[type-arg]
        context_ttl_seconds: int = 60 * 60,
    ):
        self.redis_client = redis_client
        self.context_ttl_seconds = context_ttl_seconds

    def _context_key(self, user_id: str, channel: Channel) -> str:
        return f"chat_context:{channel.value}:{user_id}"

    async def create_context(
        self,
        user_id: str,
        channel: Channel,
        state: str,
    ) -> ChatContext:
        """Create and persist a new chat context."""
        context = ChatContext(
            user_id=user_id,
            channel=channel,
            state=state,
        )

        await self.save_context(context)
        return context

    async def get_context(
        self,
        user_id: str,
        channel: Channel,
    ) -> ChatContext | None:
        """Retrieve a persisted chat context."""
        result = await self.redis_client.get(self._context_key(user_id, channel))
        context_json = cast(str | bytes | None, result)

        if not context_json:
            return None

        try:
            return ChatContext.model_validate_json(context_json)
        except (json.JSONDecodeError, ValidationError, TypeError):
            logger.exception(
                "Failed to decode chat context for user_id %s and channel %s",
                user_id,
                channel,
            )
            return None

    async def save_context(self, context: ChatContext) -> None:
        """Persist chat context with expiration."""
        try:
            await self.redis_client.set(
                self._context_key(context.user_id, context.channel),
                context.model_dump_json(),
                ex=self.context_ttl_seconds,
            )
            logger.info(
                "Saved chat context for user_id %s and channel %s",
                context.user_id,
                context.channel,
            )
        except redis.RedisError:
            logger.exception(
                "Failed to save chat context for user_id %s and channel %s",
                context.user_id,
                context.channel,
            )
            raise

    async def update_context(
        self,
        message: Message,
        state: str,
    ) -> ChatContext:
        """
        Update current state and append the received message to history.

        If context does not exist, creates a new one.
        """
        context = await self.get_context(
            user_id=message.user_id,
            channel=message.channel,
        )

        if context is None:
            context = ChatContext(
                user_id=message.user_id,
                channel=message.channel,
                state=state,
            )
        else:
            context.state = state

        context.history.append(
            {
                "origin": message.channel.value,
                "content": message.content or "",
            }
        )

        await self.save_context(context)
        return context
    
    async def delete_context(
        self,
        user_id: str,
        channel: Channel,
    ) -> bool:
        """
        Delete chat context from Redis.

        Returns True if a key was deleted, False otherwise.
        """
        key = self._context_key(user_id, channel)

        try:
            result = await self.redis_client.delete(key)
            # Redis retorna número de chaves removidas (0 ou 1 aqui)
            return result == 1
        except redis.RedisError:
            logger.exception(
                "Failed to delete chat context for user_id %s and channel %s",
                user_id,
                channel,
            )
            raise