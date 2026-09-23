"""Bounded Redis scheduler: timestamp ordering per chat and independent retry deadlines."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.domain.message import Message
from app.infra.redis_policy import MAX_RECORD_BYTES, STATE_INDEX, STATE_LUA

SCHEDULER = STATE_LUA + """
local op, now, data = ARGV[1], tonumber(ARGV[2]), cjson.decode(ARGV[3])
local limit = tonumber(ARGV[4])
local function prune(order, records, done)
    for _, id in ipairs(redis.call('ZRANGEBYSCORE', order, '-inf', now - 300)) do
        redis.call('ZREM', order, id); redis.call('HDEL', records, id)
    end
    redis.call('ZREMRANGEBYSCORE', done, '-inf', now)
end
local function add(order, records, done, item)
    if item == cjson.null or item.expires_at <= now then return 0 end
    if redis.call('ZSCORE', done, item.id) or redis.call('HEXISTS', records, item.id) == 1 then return 0 end
    if redis.call('ZCARD', order) >= limit then return -1 end
    redis.call('HSET', records, item.id, cjson.encode(item))
    redis.call('ZADD', order, item.timestamp, item.id)
    redis.call('EXPIRE', order, 3600); redis.call('EXPIRE', records, 3600)
    return 1
end
local function finish(id)
    redis.call('HDEL', KEYS[2], id); redis.call('ZREM', KEYS[1], id)
    redis.call('ZADD', KEYS[3], now + 3600, id)
    local overflow = redis.call('ZCARD', KEYS[3]) - limit
    if overflow > 0 then redis.call('ZREMRANGEBYRANK', KEYS[3], 0, overflow - 1) end
    redis.call('EXPIRE', KEYS[3], 3600)
end
prune(KEYS[1], KEYS[2], KEYS[3])
if op == 'publish' then return add(KEYS[1], KEYS[2], KEYS[3], data) end
if op == 'ack' then finish(data.id); return 1 end
if op == 'retry' then
    local raw = redis.call('HGET', KEYS[2], data.id)
    if raw then
        local item = cjson.decode(raw)
        item.available_at = data.available_at; item.leased = false
        redis.call('HSET', KEYS[2], data.id, cjson.encode(item))
    end
    return 1
end
if op == 'initialize' or op == 'claim' then
    local blocked = {}
    for _, id in ipairs(redis.call('ZRANGE', KEYS[1], 0, -1)) do
        local raw = redis.call('HGET', KEYS[2], id)
        if raw then
            local item = cjson.decode(raw)
            if op == 'initialize' and item.leased then
                item.available_at = now; item.leased = false
                redis.call('HSET', KEYS[2], id, cjson.encode(item))
            elseif op == 'claim' and not blocked[item.chat_id] then
                blocked[item.chat_id] = true
                if item.available_at <= now then
                    item.attempts = item.attempts + 1; item.available_at = now + 300; item.leased = true
                    local claimed = cjson.encode(item)
                    redis.call('HSET', KEYS[2], id, claimed)
                    return claimed
                end
            end
        else redis.call('ZREM', KEYS[1], id) end
    end
    return nil
end
if op == 'complete' then
    prune(KEYS[4], KEYS[5], KEYS[6])
    -- Capacity is checked before state/ack writes (Lua errors do not roll back mutations).
    local added = add(KEYS[4], KEYS[5], KEYS[6], data.response)
    if added == -1 then return -1 end
    for key, item in pairs(data.state) do save_state(KEYS[7], key, item, now) end
    finish(data.id)
    return 1
end
return redis.call('ZCARD', KEYS[1])
"""


@dataclass
class Delivery:
    id: str
    payload: str
    attempts: int

    @property
    def message(self) -> Message:
        return Message.model_validate_json(self.payload)


class QueueFullError(RuntimeError):
    pass


class MessageQueue:
    max_records = 512

    def __init__(self, redis_client: Redis[str], queue_name: str = "inbound") -> None:
        self.redis_client, self.queue_name = redis_client, queue_name
        self.key = f"message_queue:{queue_name}:order"
        self.keys = [self.key, f"{self.key}:records", f"{self.key}:done"]
        self._ready = False

    async def _run(self, operation: str, data: dict[str, Any], extra_keys: list[str] | None = None) -> Any:
        keys = self.keys + (extra_keys or [])
        result = await self.redis_client.eval(  # type: ignore[no-untyped-call]
            SCHEDULER, len(keys), *keys, operation, time.time(), json.dumps(data), self.max_records,
        )
        if result == -1:
            raise QueueFullError("Message queue capacity reached")
        return result

    @staticmethod
    def _record(message: Message) -> dict[str, Any] | None:
        if not message.is_recent():
            return None
        payload = message.model_dump_json()
        if len(payload.encode()) > MAX_RECORD_BYTES:
            raise ValueError("Message exceeds Redis payload limit")
        assert message.created_at is not None  # noqa: S101
        from datetime import UTC
        timestamp = message.created_at.replace(tzinfo=UTC) if message.created_at.tzinfo is None else message.created_at
        event_id = message.event_id or f"{message.channel.value}:{message.message_id}"
        return {"id": hashlib.sha256(event_id.encode()).hexdigest(), "payload": payload,
                "timestamp": timestamp.timestamp(), "expires_at": timestamp.timestamp() + 300,
                "available_at": time.time(), "chat_id": f"{message.channel.value}:{message.chat_id}", "attempts": 0}

    async def initialize(self) -> None:
        # Only the singleton worker calls this: release leases left by its previous process.
        await self._run("initialize", {})
        self._ready = True

    async def publish(self, message: Message) -> None:
        record = self._record(message)
        if record is not None:
            await self._run("publish", record)

    async def claim_next(self, timeout_seconds: int = 1) -> Delivery | None:
        if not self._ready:
            await self.initialize()
        raw = await self._run("claim", {})
        if not raw:
            return None
        item = json.loads(raw)
        return Delivery(item["id"], item["payload"], item["attempts"])

    async def retry(self, delivery: Delivery, delay: float) -> None:
        await self._run("retry", {"id": delivery.id, "available_at": time.time() + delay})

    async def ack(self, delivery: Delivery) -> None:
        await self._run("ack", {"id": delivery.id})

    async def dead_letter(self, delivery: Delivery, error: Exception) -> None:
        # Failed messages are already archived in SQL. Do not accumulate dead letters in Redis.
        await self.ack(delivery)

    async def complete_inbound(self, delivery: Delivery, result: dict[str, Any], outbound: MessageQueue) -> None:
        response = self._record(Message.model_validate(result["response"])) if result["response"] else None
        await self._run("complete", {"id": delivery.id, "state": result["state"], "response": response},
                        outbound.keys + [STATE_INDEX])

    async def get_metrics(self) -> dict[str, int]:
        return {"pending": int(await self._run("metrics", {})), "failed": 0}
