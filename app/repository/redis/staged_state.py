"""Buffer conversation state until the SQL receipt has committed."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from redis.asyncio import Redis

_changes: ContextVar[dict[str, Any] | None] = ContextVar("redis_changes", default=None)


@contextmanager
def stage_state() -> Iterator[dict[str, Any]]:
    changes: dict[str, Any] = {}
    token = _changes.set(changes)
    try:
        yield changes
    finally:
        _changes.reset(token)


class StagedState:
    def __init__(self, client: Redis[str]) -> None:
        self.client = client

    async def get(self, key: str) -> str | None:
        changes = _changes.get()
        if changes is not None and key in changes:
            item = changes[key]
            return str(item["value"]) if item else None
        return await self.client.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        changes = _changes.get()
        if changes is None:
            await self.client.set(key, value, ex=ex)
        else:
            changes[key] = {"value": value, "ttl": ex}

    async def delete(self, key: str) -> int:
        changes = _changes.get()
        if changes is None:
            return int(await self.client.delete(key))
        existed = await self.get(key) is not None
        changes[key] = None
        return int(existed)
