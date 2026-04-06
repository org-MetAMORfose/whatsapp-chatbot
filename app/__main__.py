import asyncio
import logging
import signal
import sys

from redis.asyncio import Redis, RedisError

import app.config.settings as config
from app.agent.agent_professional import AgentWorker
from app.context import AppContext
from app.message_queue import MessageQueue
from app.repository.redis_repository import ChatRepository
from app.runners.telegram_runner import TelegramRunner
from app.runners.whatsapp_runner import WhatsAppRunner
from app.services.receiver_service import MessageReceiverService

logger = logging.getLogger(__name__)


async def _async_main(app_context: AppContext) -> None:
    redis_client = Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        username=config.REDIS_USERNAME,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )

    try:
        await redis_client.ping()
    except RedisError as e:
        logger.fatal("Failed to connect to Redis: %s", e)
        sys.exit(1)

    inbound_queue = MessageQueue(redis_client, queue_name="inbound")
    outbound_queue = MessageQueue(redis_client, queue_name="outbound")

    chat_repo = ChatRepository(redis_client)

    message_receiver_service = MessageReceiverService(
        chat_repository=chat_repo,
        inbound_queue=inbound_queue,
    )

    agent_worker = AgentWorker(
        ctx=app_context,
        inbound=inbound_queue,
        outbound=outbound_queue,
        redis=redis_client,
    )

    telegram_runner = TelegramRunner(
        ctx=app_context,
        outbound_queue=outbound_queue,
        message_receiver=message_receiver_service,
        token=config.TELEGRAM_BOT_TOKEN,
    )

    whatsapp_runner = WhatsAppRunner(
        ctx=app_context,
        outbound_queue=outbound_queue,
        message_handler=message_receiver_service,
    )

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, app_context.request_shutdown)
    loop.add_signal_handler(signal.SIGTERM, app_context.request_shutdown)

    await agent_worker.start()

    if config.USE_TELEGRAM:
        await telegram_runner.start()

    if config.USE_WHATSAPP:
        await whatsapp_runner.start()

    await app_context.wait_for_shutdown()

    if config.USE_TELEGRAM:
        await telegram_runner.stop()

    if config.USE_WHATSAPP:
        await whatsapp_runner.stop()

    await agent_worker.stop()
    await redis_client.close()


def main() -> None:
    app_context = AppContext()
    asyncio.run(_async_main(app_context))


if __name__ == "__main__":
    main()