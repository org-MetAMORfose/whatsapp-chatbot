from abc import ABC, abstractmethod

from app.domain.message import Message


class BotAdapter(ABC):
    """Base adapter contract responsible for connecting to a messaging platform."""

    @abstractmethod
    async def send_message(self, message: Message) -> None:
        """Send a message to the messaging platform."""
        pass
