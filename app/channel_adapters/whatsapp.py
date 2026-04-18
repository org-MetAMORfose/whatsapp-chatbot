import logging

import httpx

import app.config.settings as config
from app.context import AppContext
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.interfaces.bot_adapter import BotAdapter

logger = logging.getLogger(__name__)


class WhatsAppAdapter(BotAdapter):
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
        self.base_url = f"https://graph.facebook.com/v23.0/{self.phone_number_id}"

    async def send_message(self, message: Message) -> None:
        if not message.chat_id:
            logger.warning("Cannot send WhatsApp message without chat_id")
            return

        if not message.content:
            logger.warning("Cannot send WhatsApp message without content")
            return

        url = f"{self.base_url}/messages"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": message.chat_id,
            "type": "text",
            "text": {
                "body": message.content,
            },
        }

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
            logger.error("Error sending WhatsApp message: %s", e, exc_info=True)
            raise