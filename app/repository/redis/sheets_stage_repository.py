"""Temporary per-user values waiting to be appended to Google Sheets."""

import hashlib
import json

import redis.asyncio as redis

from app.domain.message import Message
from app.repository.redis.staged_state import StagedState


class SheetsStageRepository:
    TTL_SECONDS = 60 * 60

    def __init__(self, redis_client: redis.Redis) -> None:  # type: ignore[type-arg]
        self.redis_client = StagedState(redis_client)

    @staticmethod
    def _key(message: Message, tab: str) -> str:
        tab_key = hashlib.sha256(tab.encode("utf-8")).hexdigest()[:24]
        return f"sheets_stage:{message.channel.value}:{message.user_id}:{tab_key}"

    async def get(self, message: Message, tab: str) -> dict[str, str]:
        raw = await self.redis_client.get(self._key(message, tab))
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in parsed.items()):
            raise ValueError("Invalid staged Google Sheets payload")
        return parsed

    async def store(self, message: Message, tab: str, column: str, value: str) -> None:
        values = await self.get(message, tab)
        values[column] = value
        await self.redis_client.set(
            self._key(message, tab),
            json.dumps(values, ensure_ascii=False),
            ex=self.TTL_SECONDS,
        )

    async def delete(self, message: Message, tab: str) -> None:
        await self.redis_client.delete(self._key(message, tab))
