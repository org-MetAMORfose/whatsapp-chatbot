from abc import ABC, abstractmethod


class BotAdapter(ABC):
    """Base adapter contract responsible for connecting to a messaging platform."""

    @abstractmethod
    async def send_message(self, chat_id: str, message: str) -> None:
        """Send a message to the messaging platform."""
        pass
