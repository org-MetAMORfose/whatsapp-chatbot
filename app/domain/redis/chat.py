from pydantic import BaseModel, Field

from app.domain.enum.channels import Channel


class ChatContext(BaseModel):
    """Represents persisted conversation state for a chat thread."""

    user_id: str
    channel: Channel
    state: str
    history: list[dict[str, str]] = Field(default_factory=list)
