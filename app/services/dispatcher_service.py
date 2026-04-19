import asyncio
import logging
from datetime import datetime

from app.context import AppContext
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.interfaces.bot_adapter import BotAdapter
from app.message_queue.message_queue import MessageQueue
from app.repository.person_repository import PersonRepository

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
            return

        await adapter.send_message(message)

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
            is_from_user=False,
        )

        self.person_repository.create_message(history_message)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())
        logger.info("Message dispatcher started, waiting for messages...")

    async def _run(self) -> None:
        while not self.ctx.is_shutting_down():
            try:
                message = await self.outbound_queue.claim_next()
                if message is None:
                    logger.debug("No message available, continuing to wait...")
                    continue

                await self.dispatch(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error dispatching message: %s", e, exc_info=True)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info("Message dispatcher stopped.")