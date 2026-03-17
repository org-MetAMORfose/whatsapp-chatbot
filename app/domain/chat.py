from dataclasses import dataclass, field


@dataclass
class ChatContext:
    """Represents persisted conversation state for a chat thread."""

    user_id: str
    chat_id: str
    state: str = "START"
    history: list[dict[str, str]] = field(default_factory=list)
