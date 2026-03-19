"""Abstract interfaces for bot runtime and message interaction context."""

from abc import ABC, abstractmethod

from app.domain.message import Message


class Bot(ABC):
    """Base bot contract responsible for starting the runtime loop."""

    @abstractmethod
    async def start(self) -> None:
        """Start the bot and wait for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the bot and clean up resources."""


class BotContext(ABC):
    """Represents contextual metadata and actions for a bot conversation."""

    chat_id: str | None
    user_id: str | None

    @abstractmethod
    async def send_message(
        self, text: str, choices: dict[str, str] | None = None
    ) -> None:
        """Send a message back to the user, optionally with choices."""

    @abstractmethod
    async def start_typing(self) -> None:
        """Notify the chat that the bot is preparing a response."""


class MessageHandler(ABC):
    """Defines callbacks to handle inbound messages and user selections."""

    @abstractmethod
    async def on_message(self, ctx: BotContext, message: Message) -> None:
        """Handle a text message received from the user."""

    @abstractmethod
    async def on_option_selected(self, option_key: str, ctx: BotContext) -> None:
        """Handle a callback option selected by the user."""
