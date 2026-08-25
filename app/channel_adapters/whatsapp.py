import io
import logging
from typing import Any

import httpx

import app.config.settings as config
from app.context import AppContext
from app.domain.enum.channels import Channel
from app.domain.message import Message, MessageButton
from app.interfaces.bot_adapter import BotAdapter
from app.services.s3_media_service import S3MediaService

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
                     image_id: str | None = None) -> dict[str, Any]:
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

    if image_id:
        payload["interactive"]["header"] = {
            "type": "image",
            "image": {
                "id": image_id
            }
        }

    return payload


def _list_message(to: str, content: str, buttons: list[MessageButton]) -> dict[str, Any]:
    rows = [
        {
            "id": button["id"],
            "title": button["title"][:24],
        }
        for button in buttons[:10]
    ]

    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": content,
            },
            "action": {
                "button": "Ver opções",
                "sections": [
                    {
                        "title": "Opções",
                        "rows": rows,
                    }
                ],
            },
        },
    }


def _image_message(to: str, caption: str, media_id: str) -> dict[str, Any]:
    image: dict[str, Any] = {"id": media_id}
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image,
    }

    if caption:
        image["caption"] = caption

    return payload


def _document_message(
    to: str,
    media_id: str,
    filename: str,
    caption: str,
) -> dict[str, Any]:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            "caption": caption,
        },
    }

    return payload


def _video_message(to: str, caption: str, media_id: str) -> dict[str, Any]:
    video: dict[str, Any] = {"id": media_id}
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": video,
    }

    if caption:
        video["caption"] = caption

    return payload


class WhatsAppAdapter(BotAdapter):
    version: str = "v25.0"
    channel: Channel = Channel.WHATSAPP

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        ctx: AppContext | None = None,
        s3_service: S3MediaService | None = None,
    ) -> None:
        self.ctx = ctx
        self.access_token = access_token or config.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or config.WHATSAPP_PHONE_NUMBER_ID
        self.base_url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}"
        self.s3_service = s3_service

    async def send_message(self, message: Message) -> None:
        if not message.chat_id:
            logger.warning("Cannot send WhatsApp message without chat_id")
            return

        url = f"{self.base_url}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        payload = await self._parse_message(message)

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

    async def _upload_media_to_whatsapp(self, media_path: str) -> str:
        """Upload media to WhatsApp and return media_id."""
        if self.s3_service is None:
            raise RuntimeError("S3 media storage is not configured")

        try:
            media_url_endpoint = f"{self.base_url}/media"
            headers = {"Authorization": f"Bearer {self.access_token}"}

            media = await self.s3_service.get_file(media_path)

            # Upload to WhatsApp using form data and file
            data = {"messaging_product": "whatsapp", "type": media.content_type}
            files = {
                "file": (
                    media.filename,
                    io.BytesIO(media.content),
                    media.content_type,
                )
            }

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    media_url_endpoint, headers=headers, data=data, files=files
                )
                if response.status_code != 200:
                    logger.error(
                        "WhatsApp media upload returned %s: %s",
                        response.status_code,
                        response.text,
                    )
                response.raise_for_status()
                resp_data = response.json()
                media_id = resp_data.get("id")
                logger.info("Uploaded media to WhatsApp, media_id=%s", media_id)
                if not isinstance(media_id, str):
                    raise RuntimeError("WhatsApp media upload did not return an id")
                return media_id

        except Exception:
            logger.exception("Error uploading media to WhatsApp")
            raise

    async def _parse_message(self, msg: Message) -> dict[str, Any]:
        if msg.buttons:
            if len(msg.buttons) <= 3:
                image_id = None
                if msg.media:
                    if S3MediaService.get_media_type(msg.media) != "image":
                        raise ValueError("interactive button media must be an image")
                    image_id = await self._upload_media_to_whatsapp(msg.media)

                return _button_message(
                    msg.chat_id,
                    msg.content or "",
                    msg.buttons,
                    image_id=image_id,
                )

            return _list_message(
                msg.chat_id,
                msg.content or "",
                msg.buttons,
            )

        if msg.media:
            media_type = S3MediaService.get_media_type(msg.media)
            media_id = await self._upload_media_to_whatsapp(msg.media)
            if media_type == "image":
                return _image_message(msg.chat_id, msg.content or "", media_id)

            if media_type == "video":
                return _video_message(msg.chat_id, msg.content or "", media_id)

            return _document_message(
                msg.chat_id,
                media_id,
                msg.media.rsplit("/", 1)[-1],
                msg.content or "",
            )

        return _text_message(msg.chat_id, msg.content or "")
