from pydantic import BaseModel, Field


class ChatContext(BaseModel):
    """Represents persisted conversation state for a chat thread."""

    user_id: str
    chat_id: str
    state: str = "START"
    history: list[dict[str, str]] = Field(default_factory=list)
