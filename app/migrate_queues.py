"""Archive old queue entries and move only fresh messages to the bounded scheduler.

Run with old/new workers stopped. Publication deduplicates before the source is deleted.
"""
import asyncio
from hashlib import sha256

from app.config.infra import create_db_engine, create_redis, create_session_factory
from app.domain.message import Message
from app.infra.message_queue import MessageQueue
from app.repository.sql.person_repository import PersonRepository
from app.services.receiver_service import MessageReceiverService


async def run() -> None:
    redis = create_redis()
    engine = create_db_engine()
    people = PersonRepository(create_session_factory(engine))
    try:
        for name in ("inbound", "outbound"):
            queue = MessageQueue(redis, name)
            receiver = MessageReceiverService(queue, people)

            async def move(raw: str, source_id: str, name: str = name,
                           receiver: MessageReceiverService = receiver, queue: MessageQueue = queue) -> None:
                message = Message.model_validate_json(raw)
                if not message.event_id:
                    message.event_id = f"legacy:{name}:{source_id}"
                if name == "inbound":
                    await receiver.handle(message)
                else:
                    await queue.publish(message)

            legacy = f"message_queue:{name}:pending"
            while raw := await redis.lindex(legacy, -1):
                await move(raw, sha256(raw.encode()).hexdigest())
                await redis.rpop(legacy)
            stream = f"message_queue:{name}:stream"
            while rows := await redis.xrange(stream, count=1):
                entry_id, values = rows[0]
                await move(values["payload"], entry_id)
                await redis.xdel(stream, entry_id)
            await redis.delete(stream, f"{stream}:attempts", f"{stream}:failed")
            async for key in redis.scan_iter(match=f"{stream}:published:*"):
                await redis.delete(key)
        # Existing conversation keys predate the bounded index: retain at most 1024, for <= 1h.
        from app.repository.redis.staged_state import StagedState
        state = StagedState(redis)
        for pattern in ("chat_context:*", "patient_stage:*", "professional_stage:*"):
            async for key in redis.scan_iter(match=pattern):
                value = await redis.get(key)
                if value is not None:
                    ttl = await redis.ttl(key)
                    await state.set(key, value, ex=min(ttl if ttl > 0 else 3600, 3600))
    finally:
        await redis.aclose()  # type: ignore[attr-defined]
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
