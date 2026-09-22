import asyncio
import logging
from datetime import datetime

from app.context import AppContext
from app.domain.db.delivery_model import InboxModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.interfaces.bot_adapter import BotAdapter
from app.message_queue.message_queue import MessageQueue
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.transaction import transaction

logger = logging.getLogger(__name__)


class MessageDispatcherService:
    """Dispatches messages from the agent worker to the appropriate channel adapters."""

    def __init__(
        self,
        ctx: AppContext,
        outbound_queue: MessageQueue,
        person_repository: PersonRepository,
    ) -> None:
        self.ctx = ctx
        self.outbound_queue = outbound_queue
        self.person_repository = person_repository
        self.channels: dict[Channel, BotAdapter] = {}
        self._task: asyncio.Task[None] | None = None

    def register_adapter(self, channel: Channel, adapter: BotAdapter) -> None:
        self.channels[channel] = adapter

    async def dispatch(self, message: Message) -> None:
        logger.info("Dispatching message: %s", message)

        adapter = self.channels.get(message.channel)
        if adapter is None:
            logger.error("No adapter found for channel %s", message.channel)
            raise ValueError(f"No adapter for {message.channel}")

        event_id = "sent:" + (message.event_id or f"{message.channel.value}:{message.message_id}")
        with self.person_repository._session_factory() as session:
            if session.get(InboxModel, event_id) is not None:
                return
        await adapter.send_message(message)
        with transaction(self.person_repository._session_factory) as session:
            person = self.person_repository.get_or_create_person(
                phone_number=message.user_id, channel=message.channel,
            )
            self.person_repository.create_message(MessageHistoryModel(
                person_id=person.id, created_at=message.created_at or datetime.utcnow(),
                content=message.content, media_path=message.media, is_from_user=False,
            ))
            session.add(InboxModel(id=event_id, result={"sent": True}))
