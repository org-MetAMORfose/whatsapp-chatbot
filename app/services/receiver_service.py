import logging
from datetime import datetime

from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.repository.person_repository import PersonRepository

logger = logging.getLogger(__name__)


class MessageReceiverService:
    def __init__(
        self,
        inbound_queue: MessageQueue,
        person_repository: PersonRepository,
    ) -> None:
        self.inbound_queue = inbound_queue
        self.person_repository = person_repository

    async def handle(self, message: Message) -> None:
        logger.info("Received message: %s", message)

        if not message.chat_id:
            logger.warning("Received message without chat_id: %s", message)
            return

        person = self.person_repository.get_or_create_person(
            phone_number=message.user_id,
            channel=message.channel,
        )

        history_message = MessageHistoryModel(
            person_id=person.id,
            created_at=message.created_at or datetime.utcnow(),
            content=message.content,
            image_url=message.image,
            document_url=message.document,
            is_from_user=True,
        )

        self.person_repository.create_message(history_message)

        if person.chat_mode == ChatMode.MANUAL:
            logger.info(
                "Skipping agent queue for person %s because the agent is in manual mode.",
                person.id,
            )
            return

        await self.inbound_queue.publish(message)
