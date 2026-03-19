"""High-level message queue API to manage AgentWorkers workloads."""

from redis.asyncio import Redis

from .models import QueuedMessage


class MessageQueue:
    """Service-style facade for pending messages and worker acknowledgements."""

    redis_client: Redis  # type: ignore[type-arg]

    def __init__(self, redis_client: Redis, queue_name: str = "agent-workers") -> None:  # type: ignore[type-arg]
        self.redis_client = redis_client
        self.queue_name = queue_name

    def _pending_key(self) -> str:
        return f"message_queue:{self.queue_name}:pending"

    async def publish(self, thread_id: str, text: str) -> QueuedMessage:
        """Create and enqueue a message to be processed by AgentWorkers."""
        message = QueuedMessage.create(thread_id=thread_id, text=text)
        await self.redis_client.lpush(self._pending_key(), message.to_json())
        return message

    async def claim_next(self, timeout_seconds: int = 0) -> QueuedMessage | None:
        """Claim next message for processing by popping from queue.

        Args:
            timeout_seconds: How long to wait for a message.
                           0 = block indefinitely (default).
        """
        result = await self.redis_client.brpop(
            self._pending_key(),
            timeout=timeout_seconds,
        )

        # brpop returns (key, value) or None if timeout
        payload = result[1] if result else None

        if payload is None:
            return None

        return QueuedMessage.from_json(payload)

    async def get_metrics(self) -> dict[str, int]:
        """Return queue metrics for pending messages."""
        pending = await self.redis_client.llen(self._pending_key())
        return {
            "pending": pending,
        }
