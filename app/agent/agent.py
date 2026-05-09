import asyncio
import logging

from app.agent.action_executor import ActionExecutor
from app.agent.chat_flow import ChatFlow
from app.context import AppContext
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.repository.professional_repository import ProfessionalRepository
from app.repository.professional_stage_repository import ProfessionalStageRepository
from app.repository.redis_repository import ChatRepository

logger = logging.getLogger(__name__)


class AgentWorker:
    ctx: AppContext
    inbound_queue: MessageQueue
    outbound_queue: MessageQueue
    flow: ChatFlow
    _task: asyncio.Task[None] | None

    def __init__(
        self,
        ctx: AppContext,
        inbound: MessageQueue,
        outbound: MessageQueue,
        chat_repository: ChatRepository,
        professional_repository: ProfessionalRepository,
        professional_stage_repository: ProfessionalStageRepository,
    ):
        self.ctx = ctx
        self.inbound_queue = inbound
        self.outbound_queue = outbound
        self.flow = ChatFlow.from_file()
        self.chat_repository = chat_repository
        professional_repository = professional_repository
        self.action_executor = ActionExecutor(professional_stage_repository)

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

                await self.outbound_queue.publish(message=response)

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

    async def _process_message(self, message: Message) -> str:
        """Process a message from the queue.

        Args:
            message: The QueuedMessage to process
        """
        if not message.content:
            logger.warning(f"Received message with no content: {message}")
            return "Mensagem vazia recebida."

        content = message.content.strip().lower()
        logger.debug("Processing message content: {content} for chat {chat_id}")

        # Use a different key for flow state to avoid conflicts with chat context
        context = await self.chat_repository.get_context(user_id=message.user_id,
                                                          channel=message.channel)
        current_state = context.state if context else None
        logger.debug("Current state from Redis: {current_state}")
        logger.debug("Available flow states: {list(self.flow.keys())}")

        if current_state is None:
            current_state = "start"
            logger.debug("Starting flow with state: {current_state}")
            node = self.flow.get(current_state)
            if node and not node.get("end"):
                await self.chat_repository.create_context(
                     user_id=message.user_id, channel=message.channel, state=current_state)
                logger.debug("Set redis flow_state to: start")
                return str(node.message)
            else:
                return "Erro ao iniciar o fluxo."

        # Continue the flow
        node = self.flow.get(current_state)
        logger.debug("Node for state {current_state}: {node}")
        if not node:
            logger.error(f"No node found for state: {current_state}")
            return "Erro no fluxo."

        if node.get("end"):
            await self.chat_repository.delete_context(user_id=message.user_id,
                                                       channel=message.channel)
            return str(node.message)

        func_output = await self.action_executor.run(node, message)
        logger.info(f"Action executor output: {node.actions} returned {func_output}")
        transition = node.next_transition(content)
        if transition is None:
            logger.error(f"Flow node {current_state} has no transition.")
            return "Erro no fluxo."

        if transition.target:
            next_node = self.flow.get(transition.target)
            logger.debug("Next node: {next_node}")
            if next_node:
                if next_node.get("end"):
                    await self.chat_repository.delete_context(user_id=message.user_id,
                                                               channel=message.channel)
                else:
                    await self.chat_repository.update_context(message, state=transition.target)
                logger.info(func_output + str(next_node.message))
                return func_output + str(next_node.message)
            else:
                logger.error(f"No node found for next_state: {transition.target}")
                return "Erro no próximo passo."
        else:
            return "Fim do fluxo."
