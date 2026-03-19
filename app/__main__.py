import asyncio
import logging
import signal
import sys

from redis.asyncio import Redis, RedisError

from app import config
from app.agent import AgentWorker
from app.bot.telegram_bot import TelegramBot
from app.chat import ChatRepository, ChatService
from app.message_queue import MessageQueue

logger = logging.getLogger(__name__)


shutdown_event = asyncio.Event()


async def _async_main() -> None:
    redis_client = Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        username=config.REDIS_USERNAME,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )

    try:
        await redis_client.ping()
        logger.info(
            "Successfully connected to Redis at %s:%d",
            config.REDIS_HOST,
            config.REDIS_PORT,
        )
    except RedisError as e:
        logger.fatal("Failed to connect to Redis: %s", e)
        sys.exit(1)

    inbound_queue = MessageQueue(redis_client, queue_name="inbound")
    outbound_queue = MessageQueue(redis_client, queue_name="outbound")
    chat_repo = ChatRepository(redis_client)
    chat_service = ChatService(chat_repository=chat_repo, inbound_queue=inbound_queue)
    agent_worker = AgentWorker(inbound=inbound_queue, outbound=outbound_queue)

    bot = TelegramBot(message_handler=chat_service)

    tasks = [
        asyncio.create_task(bot.run()),
        asyncio.create_task(agent_worker.start()),
    ]

    await shutdown_event.wait()

    for task in tasks:
        task.cancel()

    asyncio.gather(*tasks, return_exceptions=True)
    await redis_client.close()


def _shutdown() -> None:
    logger.info("Shutting down gracefully...")

    shutdown_event.set()


def main() -> None:
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, _shutdown)
    loop.add_signal_handler(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(_async_main())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
