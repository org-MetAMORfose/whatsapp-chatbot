from abc import ABC, abstractmethod


class BotAdapter(ABC):
    """Base adapter contract responsible for connecting to a messaging platform."""

    @abstractmethod
    def send_message(self, message: str) -> None:
        """Send a message to the messaging platform."""
        pass
