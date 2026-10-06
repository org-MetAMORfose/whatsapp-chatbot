"""Temporary marker for the next reply to a matching follow-up."""

import redis.asyncio as redis

from app.domain.enum.channels import Channel
from app.infra.redis_policy import MAX_STATE_TTL_SECONDS
from app.repository.redis.staged_state import StagedState


class MatchingFollowUpRepository:
    TTL_SECONDS = 3 * 24 * 60 * 60

    def __init__(self, redis_client: redis.Redis) -> None:  # type: ignore[type-arg]
        self.redis_client = StagedState(
            redis_client,
            max_ttl_seconds=MAX_STATE_TTL_SECONDS,
        )

    @staticmethod
    def _key(user_id: str, channel: Channel) -> str:
        return f"matching_follow_up:{channel.value}:{user_id}"

    async def mark(self, user_id: str, channel: Channel) -> None:
        await self.redis_client.set(
            self._key(user_id, channel),
            "pending",
            ex=self.TTL_SECONDS,
        )

    async def consume(self, user_id: str, channel: Channel) -> bool:
        key = self._key(user_id, channel)
        if await self.redis_client.get(key) is None:
            return False
        await self.redis_client.delete(key)
        return True
