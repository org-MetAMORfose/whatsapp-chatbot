import asyncio
import json
import logging

from redis.asyncio import Redis

from app.context import AppContext
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.message_queue.models import QueuedMessage

logger = logging.getLogger(__name__)


class AgentWorker:
    ctx: AppContext
    inbound_queue: MessageQueue
    outbound_queue: MessageQueue
    redis: Redis
    flow: dict
    _task: asyncio.Task[None] | None

    def __init__(
        self,
        ctx: AppContext,
        inbound: MessageQueue,
        outbound: MessageQueue,
        redis: Redis,
    ):
        self.ctx = ctx
        self.inbound_queue = inbound
        self.outbound_queue = outbound
        self.redis = redis
        with open("app/agent/flow.json", "r", encoding="utf-8") as f:
            self.flow = json.load(f)

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
                response_content = await self._process_message(message)

                response = Message(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content=response_content,
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
        content = message.content.strip().lower() if message.content else ""
        chat_id = message.chat_id
        logger.debug("Processing message content: {content} for chat {chat_id}")

        # Use a different key for flow state to avoid conflicts with chat context
        current_state = await self.redis.get(f"flow_state:{chat_id}")
        logger.debug("Current state from Redis: {current_state}")
        logger.debug("Available flow states: {list(self.flow.keys())}")

        if current_state is None:
            # Start the flow
            current_state = "start"
            logger.debug("Starting flow with state: {current_state}")
            node = self.flow.get(current_state)
            if node and not node.get("end"):
                await self.redis.set(f"flow_state:{chat_id}", "start")
                logger.debug("Set redis flow_state to: start")
                return node["message"]
            else:
                return "Erro ao iniciar o fluxo."

        # Continue the flow
        node = self.flow.get(current_state)
        logger.debug("Node for state {current_state}: {node}")
        if not node:
            logger.error(f"No node found for state: {current_state}")
            return "Erro no fluxo."

        if node.get("end"):
            await self.redis.delete(f"flow_state:{chat_id}")
            return node["message"]

        if node.get("yes") or node.get("no"):
            if content in ["sim", "yes", "s", "y"]:
                next_state = node.get("yes")
            elif content in ["não", "no", "n"]:
                next_state = node.get("no")
            else:
                return "Por favor, responda com 'sim' ou 'não' (ou 's'/'n', 'y'/'n')."
        elif node.get("next"):
            next_state = node.get("next")
        else:
            logger.error(f"Flow node {current_state} has no transition.")
            return "Erro no fluxo."

        logger.debug("Next state: {next_state}")
        if next_state:
            next_node = self.flow.get(next_state)
            logger.debug("Next node: {next_node}")
            if next_node:
                if next_node.get("end"):
                    await self.redis.delete(f"flow_state:{chat_id}")
                else:
                    await self.redis.set(f"flow_state:{chat_id}", next_state)
                return next_node["message"]
            else:
                logger.error(f"No node found for next_state: {next_state}")
                return "Erro no próximo passo."
        else:
            return "Fim do fluxo."
