import hashlib
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.dispatcher_service import MessageDispatcherService

logger = logging.getLogger(__name__)


class SendMessageRequest(BaseModel):
    phone_number: str
    content: str | None = None
    image_url: str | None = None
    document_url: str | None = None


class SendMessageController:
    def __init__(self, dispatcher: MessageDispatcherService) -> None:
        self.dispatcher = dispatcher
        self.router = APIRouter()

        self.router.add_api_route(
            "/send",
            self.send_message,
            methods=["POST"],
        )

    async def send_message(self, body: SendMessageRequest) -> dict[str, str]:
        message = Message(
            message_id=self._generate_message_id(),
            channel=Channel.WHATSAPP,
            created_at=datetime.now(UTC),
            user_id=body.phone_number,
            chat_id=body.phone_number,
            content=body.content,
            image=body.image_url,
            document=body.document_url,
        )

        await self.dispatcher.dispatch(message)

        return {"status": "ok"}

    @staticmethod
    def _generate_message_id() -> int:
        digest = hashlib.sha256(str(uuid4()).encode()).hexdigest()
        return int(digest[:12], 16)
