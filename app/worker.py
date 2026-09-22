"""Independent worker process: inbound, outbound and integration delivery loops."""
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.google_sheets_service import GoogleSheetsService

from redis.exceptions import RedisError
from sqlalchemy import text

from app.config import infra
from app.context import AppContext
from app.message_queue.message_queue import Delivery, MessageQueue
from app.repository.sql.outbox_repository import OutboxRepository
from app.worker_health import HEARTBEAT_FILE

logger = logging.getLogger(__name__)


async def consume(queue: MessageQueue, handler: Callable[[Delivery], Awaitable[None]], ctx: AppContext) -> None:
    while not ctx.is_shutting_down():
        delivery = await queue.claim_next()
        if delivery is None:
            continue
        try:
            await handler(delivery)
        except RedisError:
            # Infrastructure failure is not a poison message; restart and recover its pending entry.
            raise
        except Exception as exc:
            logger.exception("Delivery failed: queue=%s id=%s attempt=%s", queue.queue_name, delivery.id, delivery.attempts)
            if delivery.attempts >= 5:
                await queue.dead_letter(delivery, exc)
            else:
                await asyncio.sleep(min(30, 2 ** delivery.attempts))


async def relay(repository: OutboxRepository, ctx: AppContext) -> None:
    # Only this executor owns the synchronous Google client and its HTTP connections.
    service: GoogleSheetsService | None = None

    def deliver() -> bool:
        nonlocal service
        from app.services.google_sheets_service import GoogleSheetsService
        item = repository.claim()
        if item is None:
            return False
        try:
            if not item.kind.startswith("sheets."):
                raise ValueError(f"No handler registered for {item.kind}")
            if service is None:
                service = GoogleSheetsService()
            service.deliver(item.id, item.kind, item.payload)
        except Exception as exc:
            logger.exception("Outbox delivery failed: id=%s attempt=%s", item.id, item.attempts)
            repository.finish(item, exc)
        else:
            repository.finish(item)
        return True

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="outbox") as executor:
        last_cleanup = 0.0
        while not ctx.is_shutting_down():
            if loop.time() - last_cleanup > 3600:
                await loop.run_in_executor(executor, repository.cleanup)
                last_cleanup = loop.time()
            if not await loop.run_in_executor(executor, deliver):
                await asyncio.sleep(1)


async def run() -> None:
    from app.agent.agent import AgentWorker
    from app.channel_adapters.whatsapp import WhatsAppAdapter
    from app.repository.redis.chat_repository import ChatRepository
    from app.repository.redis.patient_stage_repository import PatientStageRepository
    from app.repository.redis.professional_stage_repository import ProfessionalStageRepository
    from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
    from app.repository.sql.faq_session_repository import FaqSessionRepository
    from app.repository.sql.patient_repository import PatientRepository
    from app.repository.sql.person_repository import PersonRepository
    from app.repository.sql.professional_repository import ProfessionalRepository
    from app.services.dispatcher_service import MessageDispatcherService
    from app.services.inbound_processor import InboundProcessor
    from app.services.media_factory import create_media_service

    ctx = AppContext()
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=2, thread_name_prefix="io"))
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, ctx.request_shutdown)
    redis = infra.create_redis()
    engine = infra.create_db_engine(pool_size=4)
    tasks: list[asyncio.Task[None]] = []
    owns_queues = False
    try:
        await redis.ping()
        # One worker preserves conversation ordering, including redelivery. Fail closed on lock loss.
        with engine.connect() as lock:
            if not lock.scalar(text("SELECT pg_try_advisory_lock(74203921)")):
                raise RuntimeError("Another worker already owns the queues")
            lock.commit()
            owns_queues = True
            factory = infra.create_session_factory(engine)
            inbound, outbound = MessageQueue(redis, "inbound"), MessageQueue(redis, "outbound")
            await inbound.initialize()
            await outbound.initialize()
            people = PersonRepository(factory)
            outbox = OutboxRepository(factory)
            media = create_media_service()
            agent = AgentWorker(
                ctx=ctx, inbound=inbound, outbound=outbound,
                chat_repository=ChatRepository(redis), professional_repository=ProfessionalRepository(factory),
                professional_stage_repository=ProfessionalStageRepository(redis), person_repository=people,
                patient_repository=PatientRepository(factory), patient_stage_repository=PatientStageRepository(redis),
                outbox_repository=outbox, faq_knowledge_repository=FaqKnowledgeRepository(factory),
                faq_session_repository=FaqSessionRepository(factory),
            )
            processor = InboundProcessor(factory, agent, people, inbound, outbound, media)
            dispatcher = MessageDispatcherService(ctx, outbound, people)
            dispatcher.register_adapter(WhatsAppAdapter.channel, WhatsAppAdapter(s3_service=media))

            async def send(delivery: Delivery) -> None:
                await dispatcher.dispatch(delivery.message)
                await outbound.ack(delivery)

            async def heartbeat() -> None:
                while not ctx.is_shutting_down():
                    # An invalidated lock connection must not silently reconnect without its lock.
                    if lock.invalidated:
                        raise RuntimeError("Worker ownership connection lost")
                    lock.execute(text("SELECT 1"))
                    lock.commit()
                    await redis.set("worker:heartbeat", datetime.now(UTC).isoformat(), ex=30)
                    HEARTBEAT_FILE.touch()
                    await asyncio.sleep(5)

            tasks = [asyncio.create_task(consume(inbound, processor.process, ctx)),
                     asyncio.create_task(consume(outbound, send, ctx)),
                     asyncio.create_task(relay(outbox, ctx)), asyncio.create_task(heartbeat())]
            stopping = asyncio.create_task(ctx.wait_for_shutdown())
            done, _ = await asyncio.wait([*tasks, stopping], return_when=asyncio.FIRST_COMPLETED)
            ctx.request_shutdown()
            stopping.cancel()
            failures = [task.exception() for task in done if not task.cancelled() and task.exception()]
            # Finish in-flight work where possible; unacknowledged messages survive forced termination.
            try:
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=120)
            except TimeoutError:
                logger.warning("Shutdown timeout; pending deliveries will be recovered")
            await redis.delete("worker:heartbeat")
            if failures:
                raise RuntimeError("Worker loop stopped unexpectedly") from failures[0]
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await redis.aclose()  # type: ignore[attr-defined]
        engine.dispose()
        if owns_queues:
            HEARTBEAT_FILE.unlink(missing_ok=True)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
