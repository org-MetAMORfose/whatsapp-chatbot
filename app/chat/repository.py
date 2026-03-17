"""Repository for chat state persistence."""

import json
import logging
from dataclasses import asdict
from typing import cast

import redis

from app.domain.chat import ChatContext
from app.domain.message import Message

logger = logging.getLogger(__name__)


class ChatRepository:
    """Encapsulates Redis operations for loading and saving chat state."""

    redis_client: redis.Redis

    def __init__(self, redis_client: redis.Redis):
        """Create a chat repository with an initialized Redis client."""
        self.redis_client = redis_client

    def _state_key(self, thread_id: str) -> str:
        """Build the Redis key used to store the state for a thread."""
        return f"chat_state:{thread_id}"

    async def get_state(
        self, thread_id: str, user_id: str | None = None
    ) -> ChatContext:
        """Retrieve chat state or return an empty default state."""
        result = self.redis_client.get(self._state_key(thread_id))
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
            logger.error(
                "Failed to decode state for thread_id %s: %s", thread_id, state_json
            )
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

    async def save_state(self, thread_id: str, state: ChatContext) -> None:
        """Serialize and persist chat state in Redis for the given thread."""
        state_json = json.dumps(asdict(state), ensure_ascii=False)

        try:
            self.redis_client.set(self._state_key(thread_id), state_json)
            logger.info("Saved state for thread_id %s", thread_id)
        except redis.RedisError:
            logger.exception("Failed to save state for thread_id %s", thread_id)
            raise

    async def append_message_to_history(
        self, thread_id: str, message: Message
    ) -> ChatContext:
        """Persist a new message into the conversation history for a thread."""
        context = await self.get_state(thread_id, user_id=message.user_id)
        context.history.append(
            {
                "origin": message.origin,
                "content": message.content,
            }
        )
        await self.save_state(thread_id, context)
        return context
