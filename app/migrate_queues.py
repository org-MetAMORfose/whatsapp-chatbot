"""Move legacy list queues atomically, after stopping the old application."""
import asyncio
from uuid import uuid4

from app.config.infra import create_redis

MOVE = """
local raw = redis.call('LINDEX', KEYS[1], -1)
if not raw then return 0 end
local payload = cjson.decode(raw)
payload.event_id = ARGV[1]
redis.call('XADD', KEYS[2], '*', 'payload', cjson.encode(payload))
redis.call('RPOP', KEYS[1])
return 1
"""


async def run() -> None:
    redis = create_redis()
    try:
        for name in ("inbound", "outbound"):
            moved = 0
            while await redis.eval(  # type: ignore[no-untyped-call]
                MOVE, 2, f"message_queue:{name}:pending", f"message_queue:{name}:stream", f"legacy:{uuid4()}",
            ):
                moved += 1
            print(f"Migrated {moved} {name} messages")
    finally:
        await redis.aclose()  # type: ignore[attr-defined]


if __name__ == "__main__":
    asyncio.run(run())
