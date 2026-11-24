"""Which immediate care request a professional was last offered; expires with the offer deadline."""

import redis.asyncio as redis

from app.domain.enum.channels import Channel
from app.infra.redis_policy import MAX_STATE_TTL_SECONDS
from app.repository.redis.staged_state import StagedState


class ImmediateOfferRepository:
    def __init__(self, redis_client: redis.Redis) -> None:  # type: ignore[type-arg]
        self.redis_client = StagedState(redis_client, max_ttl_seconds=MAX_STATE_TTL_SECONDS)

    @staticmethod
    def _key(user_id: str, channel: Channel) -> str:
        return f"immediate_offer:{channel.value}:{user_id}"

    async def mark(self, user_id: str, channel: Channel, request_id: int, *, ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Offer TTL must be positive")
        await self.redis_client.set(self._key(user_id, channel), str(request_id), ex=ttl_seconds)

    async def get(self, user_id: str, channel: Channel) -> int | None:
        value = await self.redis_client.get(self._key(user_id, channel))
        if value is None or not value.isdigit():
            return None
        return int(value)

    async def clear(self, user_id: str, channel: Channel) -> None:
        await self.redis_client.delete(self._key(user_id, channel))
