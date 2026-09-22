import hashlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.services.s3_media_service import S3MediaService

logger = logging.getLogger(__name__)


class SendMessageRequest(BaseModel):
    phone_number: str
    content: str | None = None
    media: str | None = None

    @field_validator("media")
    @classmethod
    def validate_media(cls, media: str | None) -> str | None:
        if media is not None:
            S3MediaService.validate_media_path(media)
        return media


class SendMessageController:
    def __init__(self, outbound_queue: MessageQueue) -> None:
        self.outbound_queue = outbound_queue
        self.router = APIRouter()

        self.router.add_api_route(
            "/send",
            self.send_message,
            methods=["POST"],
            status_code=202,
        )

    async def send_message(self, body: SendMessageRequest) -> dict[str, str]:
        message = Message(
            event_id=f"manual:{uuid4()}",
            message_id=self._generate_message_id(),
            channel=Channel.WHATSAPP,
            created_at=datetime.now(UTC),
            user_id=body.phone_number,
            chat_id=body.phone_number,
            content=body.content,
            media=body.media,
        )

        await self.outbound_queue.publish(message)

        return {"status": "accepted"}

    @staticmethod
    def _generate_message_id() -> int:
        digest = hashlib.sha256(str(uuid4()).encode()).hexdigest()
        return int(digest[:12], 16)
