"""Service layer for chat operations, orchestrating business logic and data access."""

from app.domain.message import Message
from app.message_queue import MessageQueue

from .repository import ChatRepository


class ChatService:
    """Encapsulates business logic for managing chat interactions and state."""

    def __init__(
        self,
        chat_repository: ChatRepository,
        inbound_queue: MessageQueue,
    ) -> None:

        self.chat_repository = chat_repository
        self.inbound_queue = inbound_queue

    async def add_message(self, message: Message) -> None:
        """Add a message to the chat history."""
        # This method can be used for synchronous operations if needed

        if not message.chat_id:
            raise ValueError("Message must have a chat_id to be added to history")

        thread_id = str(message.chat_id)
        await self.chat_repository.append_message_to_history(thread_id, message)
