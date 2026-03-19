import asyncio
import logging

from app.message_queue import MessageQueue
from app.message_queue.models import QueuedMessage

logger = logging.getLogger(__name__)


class AgentWorker:
    def __init__(self, inbound: MessageQueue, outbound: MessageQueue):
        self.inbound_queue = inbound
        self.outbound_queue = outbound

    async def start(self, timeout_seconds: int = 30) -> ModuleNotFoundError:
        """Start the agent worker and wait for messages in the queue.

        Args:
            timeout_seconds: How long to wait for a message before checking again.
                           Defaults to 30 seconds.
        """
        logger.info("Agent worker started, waiting for messages...")

        while True:
            try:
                # Wait for the next message in the queue
                message = await self.inbound_queue.claim_next(
                    timeout_seconds=timeout_seconds
                )

                if message is None:
                    # No message available within timeout, continue waiting
                    logger.debug("No message available, continuing to wait...")
                    continue

                logger.info(
                    f"Processing message {message.message_id} "
                    f"for thread {message.thread_id}: {message.text}"
                )

                # Process the message here
                await self._process_message(message)
                logger.info(f"Message {message.message_id} processed successfully")

            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retrying

    async def _process_message(self, message: QueuedMessage) -> None:
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
