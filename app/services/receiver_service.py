import logging

from app.domain.message import Message
from app.message_queue import MessageQueue
from app.repository.chat_repository import ChatRepository

logger = logging.getLogger(__name__)


class MessageReceiverService:
    def __init__(
        self,
        chat_repository: ChatRepository,
        inbound_queue: MessageQueue,
    ) -> None:
        self.chat_repository = chat_repository
        self.inbound_queue = inbound_queue

    async def handle(self, message: Message) -> None:
        logger.info("Received message: %s", message)

        if not message.chat_id:
            logger.warning("Received message without chat_id: %s", message)
            return

        thread_id = str(message.chat_id)

        await self.chat_repository.append_message_to_history(thread_id, message)
        await self.inbound_queue.publish(thread_id, message)