import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import app.config.settings as config
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.services.receiver_service import MessageReceiverService

logger = logging.getLogger(__name__)


class WhatsAppController:
    def __init__(self, message_handler: MessageReceiverService) -> None:
        self.message_handler = message_handler
        self.router = APIRouter()

        self.router.add_api_route(
            "/",
            self.verify_webhook,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/",
            self.receive_webhook,
            methods=["POST"],
        )

    async def verify_webhook(
        self,
        hub_mode: str | None = Query(default=None, alias="hub.mode"),
        hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
        hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
    ) -> int:
        if (
            hub_mode == "subscribe"
            and hub_verify_token == config.WHATSAPP_VERIFY_TOKEN
            and hub_challenge is not None
        ):
            return int(hub_challenge)

        raise HTTPException(status_code=403, detail="Verification failed")

    async def receive_webhook(self, request: Request) -> dict[str, str]:
        data = await request.json()

        messages = self._extract_messages(data)

        for message in messages:
            await self.message_handler.handle(message)

        return {"status": "ok"}

    def _extract_messages(self, data: dict[str, Any]) -> list[Message]:
        extracted_messages: list[Message] = []

        try:
            entries = data.get("entry", [])

            for entry in entries:
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    messages = value.get("messages", [])

                    for msg in messages:
                        parsed = self._parse_message(msg)
                        if parsed is not None:
                            extracted_messages.append(parsed)

        except Exception as e:
            logger.error("Error parsing WhatsApp webhook payload: %s", e, exc_info=True)

        return extracted_messages

    def _parse_message(self, msg: dict[str, Any]) -> Message | None:
        try:
            raw_message_id = msg.get("id")
            user_id = msg.get("from")
            timestamp = msg.get("timestamp")
            message_type = msg.get("type")

            if raw_message_id is None or user_id is None:
                logger.warning("WhatsApp message missing id or from: %s", msg)
                return None

            content: str | None = None
            image: str | None = None
            document: str | None = None

            if message_type == "text":
                content = msg.get("text", {}).get("body")

            elif message_type == "image":
                image = msg.get("image", {}).get("id")

            elif message_type == "document":
                document = msg.get("document", {}).get("id")

            else:
                logger.info("Ignoring unsupported WhatsApp message type: %s", message_type)
                return None

            created_at = None
            if timestamp is not None:
                created_at = datetime.fromtimestamp(int(timestamp), tz=UTC)

            return Message(
                message_id=self._to_int_message_id(raw_message_id),
                channel=Channel.WHATSAPP,
                created_at=created_at,
                user_id=str(user_id),
                chat_id=str(user_id),
                content=content,
                image=image,
                document=document,
            )

        except Exception as e:
            logger.error("Error parsing WhatsApp message: %s", e, exc_info=True)
            return None

    def _to_int_message_id(self, raw_message_id: str) -> int:
        digest = hashlib.sha256(raw_message_id.encode()).hexdigest()
        return int(digest[:12], 16)