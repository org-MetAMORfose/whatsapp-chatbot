import logging
from typing import Any

import httpx

import app.config.settings as config
from app.context import AppContext
from app.domain.enum.channels import Channel
from app.domain.message import Message, MessageButton
from app.interfaces.bot_adapter import BotAdapter

logger = logging.getLogger(__name__)


def _text_message(to: str, content: str) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": content,
        },
    }

    return payload


def _button_message(to: str, content: str, buttons: list[MessageButton],
                     image_url: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": content
            },
            "action": {
                "buttons": [{
                    "type": "reply",
                    "reply": {
                        "id": button["id"],
                        "title": button["title"]
                    }
                } for button in buttons]
            }
        }
    }

    if image_url:
        payload["interactive"]["header"] = {
            "type": "image",
            "image": {
                "link": image_url
            }
        }

    return payload


def _image_message(to: str, image_url: str, caption: str) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }

    return payload


def _document_message(to: str, document_url: str, caption: str) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "link": document_url,
            "filename": "document",
            "caption": caption,
        },
    }

    return payload


class WhatsAppAdapter(BotAdapter):
    version: str = "v25.0"
    channel: Channel = Channel.WHATSAPP

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        ctx: AppContext | None = None,
    ) -> None:
        self.ctx = ctx
        self.access_token = access_token or config.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or config.WHATSAPP_PHONE_NUMBER_ID
        self.base_url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}"

    async def send_message(self, message: Message) -> None:
        if not message.chat_id:
            logger.warning("Cannot send WhatsApp message without chat_id")
            return

        url = f"{self.base_url}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        payload = self._parse_message(message)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)

            response.raise_for_status()
            logger.info("WhatsApp message sent to %s", message.chat_id)

        except httpx.HTTPStatusError as e:
            logger.error(
                "WhatsApp API returned error %s: %s",
                e.response.status_code,
                e.response.text,
            )
            raise
        except Exception as e:
            logger.error("Error sending WhatsApp message: %s",
                         e, exc_info=True)
            raise

    def _parse_message(self, msg: Message) -> dict[str, Any]:
        if msg.buttons and len(msg.buttons) > 0:
            return _button_message(msg.chat_id, msg.content or "", msg.buttons, image_url=msg.image)
        elif msg.image:
            return _image_message(msg.chat_id, msg.image, msg.content or "")
        elif msg.document:
            return _document_message(msg.chat_id, msg.document, msg.content or "")

        return _text_message(msg.chat_id, msg.content or "")