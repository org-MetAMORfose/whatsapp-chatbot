"""Repository for chat state persistence."""

import json
import logging
from typing import cast

import redis.asyncio as redis

from app.domain.chat import ChatContext
from app.domain.message import Message

logger = logging.getLogger(__name__)


class ChatRepository:
    """Encapsulates Redis operations for loading and saving chat state."""

    redis_client: redis.Redis  # type: ignore[type-arg]

    def __init__(self, redis_client: redis.Redis):  # type: ignore[type-arg]
        """Create a chat repository with an initialized Redis client."""
        self.redis_client = redis_client

    def _state_key(self, thread_id: str) -> str:
        """Build the Redis key used to store the state for a thread."""
        return f"chat_state:{thread_id}"

    async def get_chat_context(self, thread_id: str, user_id: str | None = None) -> ChatContext:
        """Retrieve chat state or return an empty default state."""
        result = await self.redis_client.get(self._state_key(thread_id))
        state_json = cast(str | None, result)

        if not state_json:
            return ChatContext(
                user_id=user_id or thread_id,
                chat_id=thread_id,
            )

        try:
            state_dict = json.loads(state_json)
            if "user_id" not in state_dict:
                state_dict["user_id"] = user_id or thread_id
            return ChatContext(**state_dict)
        except json.JSONDecodeError:
            logger.error("Failed to decode state for thread_id %s: %s", thread_id, state_json)
            return ChatContext(
                user_id=user_id or thread_id,
                chat_id=thread_id,
            )
        except TypeError:
            logger.error(
                "State payload has unexpected shape for thread_id %s: %s",
                thread_id,
                state_json,
            )
            return ChatContext(
                user_id=user_id or thread_id,
                chat_id=thread_id,
            )

    async def save_chat_context(self, thread_id: str, context: ChatContext) -> None:
        """Serialize and persist chat context in Redis for the given thread."""
        context_json = context.model_dump_json()

        try:
            await self.redis_client.set(self._state_key(thread_id), context_json)
            logger.info("Saved chat context for thread_id %s", thread_id)
        except redis.RedisError:
            logger.exception("Failed to save state for thread_id %s", thread_id)
            raise

    async def append_message_to_history(self, thread_id: str, message: Message) -> ChatContext:
        """Persist a new message into the conversation history for a thread."""
        context = await self.get_chat_context(thread_id, user_id=message.user_id)
        context.history.append(
            {
                "origin": message.channel,
                "content": message.content or "",
            }
        )
        await self.save_chat_context(thread_id, context)
        return context
