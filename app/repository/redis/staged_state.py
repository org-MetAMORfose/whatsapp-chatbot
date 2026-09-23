"""Buffer conversation state until the SQL receipt has committed."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from redis.asyncio import Redis

from app.infra.redis_policy import MAX_RECORD_BYTES, STATE_INDEX, STATE_LUA

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
        if len(value.encode()) > MAX_RECORD_BYTES:
            raise ValueError("Conversation state exceeds Redis payload limit")
        ex = min(ex, 3600)
        changes = _changes.get()
        if changes is None:
            await self.client.eval(  # type: ignore[no-untyped-call]
                STATE_LUA + "save_state(KEYS[1], KEYS[2], cjson.decode(ARGV[1]), tonumber(ARGV[2]))",
                2, STATE_INDEX, key, json.dumps({"value": value, "ttl": ex}), time.time(),
            )
        else:
            changes[key] = {"value": value, "ttl": ex}

    async def delete(self, key: str) -> int:
        changes = _changes.get()
        if changes is None:
            return int(await self.client.delete(key))
        existed = await self.get(key) is not None
        changes[key] = None
        return int(existed)
