import asyncio
import logging
import signal
import sys

from redis.asyncio import Redis, RedisError

from app import config
from app.adapters.telegram import TelegramAdapter
from app.agent.agent import AgentWorker
from app.chat import ChatRepository, ChatService
from app.context import AppContext
from app.message_queue import MessageQueue
from app.messaging import MessageDispatcher, MessageReceiver

logger = logging.getLogger(__name__)


async def _async_main(app_context: AppContext) -> None:
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
    message_receiver = MessageReceiver(
        inbound_queue=inbound_queue,
        chat_service=chat_service,
    )
    message_dispatcher = MessageDispatcher(
        ctx=app_context,
        outbound_queue=outbound_queue,
        telegram_adapter=TelegramAdapter(
            ctx=app_context,
            token=config.TELEGRAM_BOT_TOKEN,
        ),
    )

    agent_worker = AgentWorker(
        ctx=app_context,
        inbound=inbound_queue,
        outbound=outbound_queue,
    )

    telegram_adapter = TelegramAdapter(
        ctx=app_context,
        token=config.TELEGRAM_BOT_TOKEN,
    )

    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, app_context.request_shutdown)
    loop.add_signal_handler(signal.SIGTERM, app_context.request_shutdown)

    await agent_worker.start()
    await message_dispatcher.start()
    await telegram_adapter.start_listener(callback=message_receiver.callback)

    await app_context.wait_for_shutdown()

    await telegram_adapter.stop_listener()
    await agent_worker.stop()
    await message_dispatcher.stop()
    await redis_client.close()


def main() -> None:
    app_context = AppContext()
    asyncio.run(_async_main(app_context))


if __name__ == "__main__":
    main()
