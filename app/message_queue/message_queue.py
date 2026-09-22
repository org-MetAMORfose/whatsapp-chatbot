"""Redis Streams queues. One worker owns each consumer group in this deployment."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.domain.message import Message

PUBLISH = """
if redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
local id = redis.call('XADD', KEYS[1], '*', 'payload', ARGV[1])
redis.call('SET', KEYS[2], id, 'EX', ARGV[2])
return 1
"""


@dataclass
class Delivery:
    id: str
    payload: str
    attempts: int

    @property
    def message(self) -> Message:
        return Message.model_validate_json(self.payload)


class MessageQueue:
    group = "workers"
    dedup_seconds = 30 * 86400

    def __init__(self, redis_client: Redis[str], queue_name: str = "inbound") -> None:
        self.redis_client = redis_client
        self.queue_name = queue_name
        self.key = f"message_queue:{queue_name}:stream"
        self.consumer = uuid4().hex
        self._ready = False

    async def initialize(self) -> None:
        try:
            await self.redis_client.xgroup_create(self.key, self.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self._ready = True

    async def publish(self, message: Message) -> None:
        event_id = message.event_id or f"{message.channel.value}:{message.message_id}"
        await self.redis_client.eval(  # type: ignore[no-untyped-call]
            PUBLISH, 2, self.key, f"{self.key}:published:{event_id}",
            message.model_dump_json(), self.dedup_seconds,
        )

    async def claim_next(self, timeout_seconds: int = 1) -> Delivery | None:
        if not self._ready:
            await self.initialize()
        # The process-wide PostgreSQL advisory lock excludes other workers.
        # Always drain the oldest pending entry before accepting new work.
        pending = await self.redis_client.xpending_range(self.key, self.group, "-", "+", 1)
        if pending:
            records = await self.redis_client.xclaim(  # type: ignore[no-untyped-call]
                self.key, self.group, self.consumer, 0, [pending[0]["message_id"]],
            )
        else:
            batches = await self.redis_client.xreadgroup(
                self.group, self.consumer, {self.key: ">"}, count=1,
                block=max(1, timeout_seconds * 1000),
            )
            records = batches[0][1] if batches else []
        if not records:
            return None
        entry_id, fields = records[0]
        attempts = await self.redis_client.hincrby(f"{self.key}:attempts", entry_id, 1)
        return Delivery(entry_id, fields.get("payload", ""), int(attempts))

    def finish_commands(self, pipe: Any, delivery: Delivery) -> None:
        pipe.xack(self.key, self.group, delivery.id)
        pipe.xdel(self.key, delivery.id)
        pipe.hdel(f"{self.key}:attempts", delivery.id)

    async def ack(self, delivery: Delivery) -> None:
        async with self.redis_client.pipeline(transaction=True) as pipe:
            self.finish_commands(pipe, delivery)
            await pipe.execute()

    async def dead_letter(self, delivery: Delivery, error: Exception) -> None:
        async with self.redis_client.pipeline(transaction=True) as pipe:
            pipe.xadd(f"{self.key}:failed", {
                "payload": delivery.payload, "attempts": str(delivery.attempts),
                "error": type(error).__name__, "source_id": delivery.id,
            }, maxlen=1000, approximate=False)
            self.finish_commands(pipe, delivery)
            await pipe.execute()

    async def complete_inbound(self, delivery: Delivery, result: dict[str, Any], outbound: "MessageQueue") -> None:
        async with self.redis_client.pipeline(transaction=True) as pipe:
            for key, item in result["state"].items():
                if item is None:
                    pipe.delete(key)
                else:
                    pipe.set(key, item["value"], ex=item["ttl"])
            if result["response"] is not None:
                pipe.xadd(outbound.key, {"payload": json.dumps(result["response"])})
            self.finish_commands(pipe, delivery)
            await pipe.execute()

    async def get_metrics(self) -> dict[str, int]:
        return {"pending": int(await self.redis_client.xlen(self.key)),
                "failed": int(await self.redis_client.xlen(f"{self.key}:failed"))}
