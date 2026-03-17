import logging
import sys

import redis

from app import config
from app.bot.telegram_bot import TelegramBot
from app.chat import ChatRepository, ChatService
from app.message_queue import MessageQueue

logger = logging.getLogger(__name__)


def main() -> None:
    redis_client = redis.Redis(
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
        redis_client.ping()
        logger.info(
            "Successfully connected to Redis at %s:%d",
            config.REDIS_HOST,
            config.REDIS_PORT,
        )
    except redis.RedisError as e:
        logger.fatal("Failed to connect to Redis: %s", e)
        sys.exit(1)

    message_queue = MessageQueue(redis_client)
    chat_repo = ChatRepository(redis_client)
    chat_service = ChatService(chat_repository=chat_repo, message_queue=message_queue)

    app = TelegramBot(message_handler=chat_service)

    app.run()


if __name__ == "__main__":
    main()
