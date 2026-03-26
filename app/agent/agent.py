import asyncio
import logging

from app.context import AppContext
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.message_queue.models import QueuedMessage

logger = logging.getLogger(__name__)


class AgentWorker:
    ctx: AppContext
    inbound_queue: MessageQueue
    outbound_queue: MessageQueue
    _task: asyncio.Task[None] | None

    def __init__(
        self,
        ctx: AppContext,
        inbound: MessageQueue,
        outbound: MessageQueue,
    ):
        self.ctx = ctx
        self.inbound_queue = inbound
        self.outbound_queue = outbound

    async def start(
        self,
    ) -> None:
        """Start the agent worker and wait for messages in the queue.

        Args:
            timeout_seconds: How long to wait for a message before checking again.
                           Defaults to 30 seconds.
        """
        self._task = asyncio.create_task(self._run())
        logger.info("Agent worker started, waiting for messages...")

    async def _run(self) -> None:
        while not self.ctx.is_shutting_down():
            try:
                # Wait for the next message in the queue
                message = await self.inbound_queue.claim_next()

                if message is None:
                    # No message available within timeout, continue waiting
                    logger.debug("No message available, continuing to wait...")
                    continue

                thread_id = f"{message.chat_id}"

                # Process the message here
                # response = await self._process_message(message)

                response = Message(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content=f"Processed: {message.content}",
                    user_id="AGENT",
                    created_at=None,
                    message_id=0,
                )

                logger.info(f"Message {message.message_id} processed successfully")

                await self.outbound_queue.publish(thread_id=thread_id, message=response)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
        logger.info("Agent worker shutting down...")

    async def stop(self) -> None:
        """Stop the agent worker gracefully."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Agent worker stopped gracefully.")

    async def _process_message(self, message: QueuedMessage) -> str:
        """Process a message from the queue.

        Args:
            message: The QueuedMessage to process
        """
        # TODO: Implement actual message processing logic
        # This could involve:
        # - Running the agent's AI logic
        # - Calling external APIs
        # - Sending responses back to the user
        logger.debug(f"Processing message content: {message.text}")

        return f"Processed: {message.text}"
