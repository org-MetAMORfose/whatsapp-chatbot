import asyncio
import logging

from app.adapters import BotAdapter
from app.adapters.telegram import TelegramAdapter
from app.context import AppContext
from app.domain.channels import Channel
from app.domain.message import Message
from app.message_queue.message_queue import MessageQueue

logger = logging.getLogger(__name__)


class MessageDispatcher:
    """Dispatches messages from the agent worker to the appropriate channel adapters."""

    channels: dict[Channel, BotAdapter | None]
    _task: asyncio.Task[None] | None

    def __init__(
        self,
        ctx: AppContext,
        outbound_queue: MessageQueue,
        telegram_adapter: TelegramAdapter | None = None,
    ) -> None:
        self.ctx = ctx
        self.outbound_queue = outbound_queue
        self.channels = {
            Channel.TELEGRAM: telegram_adapter,
        }

    async def dispatch(self, message: Message) -> None:
        """Dispatch a message to the appropriate channel adapter."""
        logger.info(f"Dispatching message: {message}")

        adapter = self.channels.get(message.channel)

        if adapter is None:
            logger.error(f"No adapter found for channel {message.channel}")
            return

        await adapter.send_message(message)

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
                logger.error(f"Error dispatching message: {e}", exc_info=True)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await self._task
        logger.info("Message dispatcher stopped.")
