"""High-level message queue API to manage AgentWorkers workloads."""

from redis.asyncio import Redis

from app.domain.message import Message


class MessageQueue:
    """Service-style facade for pending messages and worker acknowledgements."""

    redis_client: Redis  # type: ignore[type-arg]

    def __init__(self, redis_client: Redis, queue_name: str = "agent-workers") -> None:  # type: ignore[type-arg]
        self.redis_client = redis_client
        self.queue_name = queue_name

    def _pending_key(self) -> str:
        return f"message_queue:{self.queue_name}:pending"

    async def publish(self, thread_id: str, message: Message) -> None:
        """Create and enqueue a message to be processed by AgentWorkers."""
        json_str = message.model_dump_json()
        await self.redis_client.lpush(self._pending_key(), json_str)

    async def claim_next(self, timeout_seconds: int = 0) -> Message | None:
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

        return Message.model_validate_json(payload)

    async def get_metrics(self) -> dict[str, int]:
        """Return queue metrics for pending messages."""
        pending = await self.redis_client.llen(self._pending_key())
        return {
            "pending": pending,
        }
