"""Drive isolated runtime_worker containers; all URLs must point at test infrastructure."""
import asyncio
import os
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import create_engine, text

from app.domain.enum.channels import Channel
from app.domain.redis.chat import ChatContext
from app.domain.redis.patient_stage import PatientStageContext


async def main() -> None:
    redis = Redis.from_url(os.environ["DELIVERY_TEST_REDIS_URL"], decode_responses=True)
    engine = create_engine(os.environ["DELIVERY_TEST_DATABASE_URL"])
    prefix = uuid4().hex
    sent_before = int(await redis.get("test:sent") or 0)
    count = int(os.getenv("DELIVERY_TEST_COUNT", "100"))
    async with httpx.AsyncClient(base_url=os.environ["DELIVERY_TEST_API_URL"]) as client:
        for i in range(count):
            user = f"55119{i:08d}"
            await redis.set(f"chat_context:WHATSAPP:{user}", ChatContext(
                user_id=user, channel=Channel.WHATSAPP, state="paciente_faixa_valor",
            ).model_dump_json())
            await redis.set(f"patient_stage:Channel.WHATSAPP:{user}", PatientStageContext(
                user_id=user, chat_id=user, channel=Channel.WHATSAPP,
                name="Test", area="Psicoterapia", birth_date=date(2000, 1, 1),
            ).model_dump_json())
            payload = {"entry": [{"changes": [{"value": {"messages": [{
                "id": f"{prefix}:{i}", "from": user, "timestamp": str(int(datetime.now(UTC).timestamp())),
                "type": "text", "text": {"body": "Até R$300"},
            }]}}]}]}
            response = await client.post("/", json=payload)
            response.raise_for_status()
            duplicate = await client.post("/", json=payload)
            duplicate.raise_for_status()
    for _ in range(120):
        with engine.connect() as connection:
            completed = connection.scalar(text("SELECT count(*) FROM outbox WHERE id LIKE :prefix AND status='sent'"),
                                          {"prefix": f"whatsapp:{prefix}:%"})
        sent = int(await redis.get("test:sent") or 0) - sent_before
        if completed == count and sent == count:
            break
        await asyncio.sleep(1)
    else:
        raise RuntimeError(f"Load did not drain: outbox={completed}, sent={sent}")
    with engine.connect() as connection:
        receipts = connection.scalar(text("SELECT count(*) FROM inbox WHERE id LIKE :prefix"), {"prefix": f"whatsapp:{prefix}:%"})
    if receipts != count:
        raise RuntimeError(f"Expected {count} unique receipts; got {receipts}")
    print(f"{2 * count} webhooks, {receipts} unique inputs, {sent} responses, {completed} outbox deliveries")
    await redis.aclose()
    engine.dispose()


if __name__ == "__main__":
    if os.environ.get("DELIVERY_RUNTIME_TEST") != "1":
        raise SystemExit("Only run against isolated test infrastructure")
    asyncio.run(main())
