"""High-level message queue API to manage AgentWorkers workloads."""

from typing import cast

import redis

from .models import QueuedMessage


class MessageQueue:
    """Service-style facade for pending messages and worker acknowledgements."""

    redis_client: redis.Redis

    def __init__(
        self, redis_client: redis.Redis, queue_name: str = "agent-workers"
    ) -> None:
        self.redis_client = redis_client
        self.queue_name = queue_name

    def _pending_key(self) -> str:
        return f"message_queue:{self.queue_name}:pending"

    def _processing_key(self) -> str:
        return f"message_queue:{self.queue_name}:processing"

    async def publish(self, thread_id: str, text: str) -> QueuedMessage:
        """Create and enqueue a message to be processed by AgentWorkers."""
        message = QueuedMessage.create(thread_id=thread_id, text=text)
        self.redis_client.lpush(self._pending_key(), message.to_json())
        return message

    async def claim_next(self, timeout_seconds: int = 0) -> QueuedMessage | None:
        """Claim next message for processing and move it to in-flight state."""
        payload: str | None
        if timeout_seconds > 0:
            result = self.redis_client.brpoplpush(
                src=self._pending_key(),
                dst=self._processing_key(),
                timeout=timeout_seconds,
            )
            payload = cast(str | None, result)
        else:
            result = self.redis_client.rpoplpush(
                self._pending_key(),
                self._processing_key(),
            )
            payload = cast(str | None, result)

        if payload is None:
            return None

        return QueuedMessage.from_json(payload)

    async def ack(self, message: QueuedMessage) -> bool:
        """Mark a claimed message as processed successfully."""
        removed = self.redis_client.lrem(
            self._processing_key(),
            count=1,
            value=message.to_json(),
        )
        removed_count = cast(int, removed)
        return removed_count > 0

    async def nack(self, message: QueuedMessage) -> None:
        """Mark processing failure and return message to pending queue."""
        payload = message.to_json()
        self.redis_client.lrem(self._processing_key(), count=1, value=payload)
        self.redis_client.rpush(self._pending_key(), payload)

    async def get_metrics(self) -> dict[str, int]:
        """Return queue metrics for pending and in-flight messages."""
        pending = cast(int, self.redis_client.llen(self._pending_key()))
        processing = cast(int, self.redis_client.llen(self._processing_key()))
        return {
            "pending": pending,
            "processing": processing,
        }
