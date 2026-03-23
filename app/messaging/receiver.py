import logging

from app.chat import ChatService
from app.domain.message import Message
from app.message_queue import MessageQueue

logger = logging.getLogger(__name__)


class MessageReceiver:
    def __init__(
        self,
        chat_service: ChatService,
        inbound_queue: MessageQueue,
    ):
        self.inbound_queue = inbound_queue
        self.chat_service = chat_service

    async def callback(self, message: Message) -> None:
        logger.info("Received message: %s", message)

        if not message.chat_id:
            logger.warning("Received message without chat_id: %s", message)
            return

        await self.chat_service.add_message(message)

        thread_id = str(message.chat_id)
        await self.inbound_queue.publish(thread_id, message)
