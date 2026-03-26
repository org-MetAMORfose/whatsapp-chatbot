import asyncio
import logging

from app.context import AppContext
from app.message_queue import MessageQueue
from app.message_queue.models import QueuedMessage

logger = logging.getLogger(__name__)


class AgentWorker:
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
        
        logger.info("Agent worker started, waiting for messages...")

        while not self.ctx.is_shutting_down():
            try:
                # Wait for the next message in the queue
                message = await self.inbound_queue.claim_next()

                if message is None:
                    # No message available within timeout, continue waiting
                    logger.debug("No message available, continuing to wait...")
                    continue

                logger.info(
                    f"Processing message {message.message_id} "
                    f"for thread {message.thread_id}: {message.text}"
                )

                # Process the message here
                response = await self._process_message(message)
                logger.info(f"Message {message.message_id} processed successfully")

                await self.outbound_queue.publish(
                    thread_id=message.thread_id, text=response
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
        logger.info("Agent worker shutting down...")

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
