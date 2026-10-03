import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

import app.config.settings as config
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.receiver_service import MessageReceiverService
from app.services.s3_media_service import MediaType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedWhatsAppMessage:
    message: Message
    media_id: str | None = None
    media_type: MediaType | None = None


class WhatsAppController:
    def __init__(
        self,
        message_handler: MessageReceiverService,
        outbox_repository: OutboxRepository | None = None,
    ) -> None:
        self.message_handler = message_handler
        self.outbox_repository = outbox_repository
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
        if hub_mode == "subscribe" and hub_verify_token == config.WHATSAPP_VERIFY_TOKEN and hub_challenge is not None:
            return int(hub_challenge)

        raise HTTPException(status_code=403, detail="Verification failed")

    async def receive_webhook(self, request: Request) -> dict[str, str]:
        data = await request.json()

        logger.debug("Received WhatsApp webhook payload: %s", data)
        self._log_delivery_statuses(data)

        parsed_messages = self._extract_messages(data)

        for parsed in parsed_messages:
            message = parsed.message
            message = message.model_copy(
                update={
                    "media_id": parsed.media_id,
                    "media_type": parsed.media_type,
                }
            )
            await self.message_handler.handle(message)

        return {"status": "ok"}

    def _log_delivery_statuses(self, data: dict[str, Any]) -> None:
        """Record asynchronous delivery results returned by WhatsApp."""
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for delivery in value.get("statuses", []):
                    status = delivery.get("status")
                    log = logger.warning if status == "failed" else logger.info
                    log(
                        "WhatsApp delivery status: message_id=%s status=%s recipient_id=%s timestamp=%s errors=%s",
                        delivery.get("id"),
                        status,
                        delivery.get("recipient_id"),
                        delivery.get("timestamp"),
                        delivery.get("errors") or [],
                    )
                    callback_data = delivery.get("biz_opaque_callback_data")
                    if self.outbox_repository is not None and isinstance(callback_data, str) and isinstance(status, str):
                        operation_id, separator, attempt_text = callback_data.rpartition("|")
                        if not separator or not attempt_text.isdigit():
                            continue
                        errors = delivery.get("errors") or []
                        completed = self.outbox_repository.finish_whatsapp_delivery(
                            operation_id,
                            int(attempt_text),
                            status,
                            str(errors) if errors else None,
                            max_attempts=5,
                        )
                        if completed:
                            logger.info(
                                "WhatsApp outbox receipt applied: id=%s attempt=%s status=%s",
                                operation_id,
                                attempt_text,
                                status,
                            )

    def _extract_messages(self, data: dict[str, Any]) -> list[_ParsedWhatsAppMessage]:
        extracted_messages: list[_ParsedWhatsAppMessage] = []

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

    def _parse_message(self, msg: dict[str, Any]) -> _ParsedWhatsAppMessage | None:
        try:
            raw_message_id = msg.get("id")
            user_id = msg.get("from")
            timestamp = msg.get("timestamp")
            message_type = msg.get("type")

            if raw_message_id is None or user_id is None:
                logger.warning("WhatsApp message missing id or from: %s", msg)
                return None

            content: str | None = None
            media_id: str | None = None
            media_type: MediaType | None = None

            if message_type == "text":
                content = msg.get("text", {}).get("body")

            elif message_type == "button":
                content = msg.get("button", {}).get("text")

            elif message_type == "interactive":
                interactive = msg.get("interactive", {})
                interactive_type = interactive.get("type")

                if interactive_type == "button_reply":
                    content = interactive.get("button_reply", {}).get("title")

                elif interactive_type == "list_reply":
                    content = interactive.get("list_reply", {}).get("title")

                else:
                    logger.info(
                        "Ignoring unsupported WhatsApp interactive type: %s",
                        interactive_type,
                    )
                    return None

            elif message_type == "image":
                media_id = msg.get("image", {}).get("id")
                media_type = "image"

            elif message_type == "document":
                media_id = msg.get("document", {}).get("id")
                media_type = "document"

            elif message_type == "video":
                video = msg.get("video", {})
                media_id = video.get("id")
                media_type = "video"
                content = video.get("caption")

            else:
                logger.info("Ignoring unsupported WhatsApp message type: %s", message_type)
                return None

            if media_type is not None and not media_id:
                logger.warning("WhatsApp media message missing media id: %s", msg)
                return None

            created_at = None
            if timestamp is not None:
                created_at = datetime.fromtimestamp(int(timestamp), tz=UTC)

            return _ParsedWhatsAppMessage(
                message=Message(
                    event_id=f"whatsapp:{raw_message_id}",
                    message_id=self._to_int_message_id(raw_message_id),
                    channel=Channel.WHATSAPP,
                    created_at=created_at,
                    user_id=str(user_id),
                    chat_id=str(user_id),
                    content=content,
                ),
                media_id=media_id,
                media_type=media_type,
            )

        except Exception as e:
            logger.error("Error parsing WhatsApp message: %s", e, exc_info=True)
            return None

    def _to_int_message_id(self, raw_message_id: str) -> int:
        digest = hashlib.sha256(raw_message_id.encode()).hexdigest()
        return int(digest[:12], 16)
