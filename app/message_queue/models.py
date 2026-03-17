"""Domain models for the AgentWorkers message queue."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class QueuedMessage:
    """Represents a single message scheduled for AgentWorkers processing."""

    message_id: str
    thread_id: str
    text: str
    created_at: str

    @classmethod
    def create(cls, thread_id: str, text: str) -> "QueuedMessage":
        """Build a queue message with generated id and UTC timestamp."""
        return cls(
            message_id=str(uuid4()),
            thread_id=thread_id,
            text=text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_json(self) -> str:
        """Serialize this message into a deterministic JSON payload."""
        return json.dumps(
            {
                "message_id": self.message_id,
                "thread_id": self.thread_id,
                "text": self.text,
                "created_at": self.created_at,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, payload: str) -> "QueuedMessage":
        """Deserialize a queue payload into a QueuedMessage instance."""
        data = json.loads(payload)
        return cls(
            message_id=data["message_id"],
            thread_id=data["thread_id"],
            text=data["text"],
            created_at=data["created_at"],
        )
