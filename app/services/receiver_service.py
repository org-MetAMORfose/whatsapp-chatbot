"""Webhook ingress: acknowledge only after Redis accepts the event."""
from app.domain.message import Message
from app.message_queue import MessageQueue


class MessageReceiverService:
    def __init__(self, inbound_queue: MessageQueue) -> None:
        self.inbound_queue = inbound_queue

    async def handle(self, message: Message) -> None:
        if not message.chat_id:
            raise ValueError("Message requires chat_id")
        await self.inbound_queue.publish(message)
