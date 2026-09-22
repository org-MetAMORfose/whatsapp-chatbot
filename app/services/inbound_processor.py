"""Transactional processing with replayable replies and buffered Redis state."""
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent.agent import AgentWorker
from app.domain.db.delivery_model import InboxModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message, MessageButton
from app.message_queue.message_queue import Delivery, MessageQueue
from app.repository.redis.staged_state import stage_state
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.transaction import transaction
from app.services.s3_media_service import S3MediaService


class InboundProcessor:
    def __init__(self, factory: Callable[[], Session], agent: AgentWorker, person_repository: PersonRepository,
                 inbound: MessageQueue, outbound: MessageQueue, media: S3MediaService | None) -> None:
        self.factory, self.agent, self.people = factory, agent, person_repository
        self.inbound, self.outbound, self.media = inbound, outbound, media

    async def process(self, delivery: Delivery) -> None:
        message = delivery.message
        event_id = message.event_id or f"{message.channel.value}:{message.message_id}"
        with self.factory() as session:
            receipt = session.get(InboxModel, event_id)
        if receipt is not None:
            # A repeated webhook is a different stream entry: never restore old conversation state.
            if receipt.result["delivery_id"] == delivery.id:
                await self.inbound.complete_inbound(delivery, receipt.result, self.outbound)
            else:
                await self.inbound.ack(delivery)
            return

        if message.media_id is not None and message.media is None:
            if self.media is None or message.media_type is None:
                raise RuntimeError("S3 media storage is not configured")
            path = await self.media.upload_from_whatsapp(message.media_id, message.media_type)
            message = message.model_copy(update={"media": path})

        with stage_state() as state, transaction(self.factory) as session:
            person = self.people.get_or_create_person(message.user_id, message.channel)
            if message.history_id is None:
                history = self.people.create_message(MessageHistoryModel(
                    person_id=person.id, created_at=message.created_at or datetime.utcnow(),
                    content=message.content, media_path=message.media, is_from_user=True,
                ))
                message = message.model_copy(update={"history_id": history.id})
            response: Message | None = None
            if person.chat_mode != ChatMode.MANUAL:
                answer = await self.agent._process_message(message)
                buttons: list[MessageButton] | None = (
                    [MessageButton(id=str(uuid4()), title=title) for title in answer.buttons] if answer.buttons else None
                )
                response = Message(
                    event_id=f"reply:{event_id}", message_id=message.message_id, created_at=None,
                    channel=message.channel, user_id=message.user_id, chat_id=message.chat_id,
                    content=answer.content, buttons=buttons,
                )
            result: dict[str, Any] = {
                "delivery_id": delivery.id, "state": state,
                "response": response.model_dump(mode="json") if response else None,
            }
            session.add(InboxModel(id=event_id, result=result))
        await self.inbound.complete_inbound(delivery, result, self.outbound)
