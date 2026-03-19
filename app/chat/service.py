"""Service layer for chat operations, orchestrating business logic and data access."""

from app.bot import BotContext, MessageHandler
from app.domain.message import Message
from app.message_queue import MessageQueue

from .repository import ChatRepository


class ChatService(MessageHandler):
    """Encapsulates business logic for managing chat interactions and state."""

    def __init__(
        self,
        chat_repository: ChatRepository,
        inbound_queue: MessageQueue,
    ) -> None:

        self.chat_repository = chat_repository
        self.inbound_queue = inbound_queue

    async def on_message(self, ctx: BotContext, message: Message) -> None:
        """Handle incoming messages, update chat state, and enqueue for processing."""
        thread_id = str(ctx.chat_id) if ctx.chat_id else "default"

        await self.chat_repository.append_message_to_history(thread_id, message)

        # Enqueue the message for processing by the agent workers
        await self.inbound_queue.publish(thread_id=thread_id, text=message.content)

    async def on_option_selected(self, option_key: str, ctx: BotContext) -> None: ...
