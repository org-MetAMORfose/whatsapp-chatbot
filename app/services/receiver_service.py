"""Persist every incoming message; only fresh messages enter the processing queue."""
from datetime import datetime

from sqlalchemy import select

from app.domain.db.delivery_model import InboxModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.message import Message
from app.infra.message_queue import MessageQueue
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.transaction import transaction


class MessageReceiverService:
    def __init__(self, inbound_queue: MessageQueue, person_repository: PersonRepository) -> None:
        self.inbound_queue, self.people = inbound_queue, person_repository

    async def handle(self, message: Message) -> None:
        if not message.chat_id:
            raise ValueError("Message requires chat_id")
        event_id = message.event_id or f"{message.channel.value}:{message.message_id}"
        with transaction(self.people._session_factory) as session:
            # Serialize concurrent copies of the same webhook before checking the receipt.
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                from sqlalchemy import text
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"), {"id": event_id})
            receipt = session.get(InboxModel, f"received:{event_id}")
            if receipt is None:
                person = self.people.get_or_create_person(message.user_id, message.channel)
                history = session.get(MessageHistoryModel, message.history_id) if message.history_id else None
                if history is None or history.person_id != person.id:
                    history = self.people.create_message(MessageHistoryModel(
                        person_id=person.id, created_at=message.created_at or datetime.utcnow(),
                        content=message.content, media_path=message.media, is_from_user=True,
                    ))
                receipt = InboxModel(id=f"received:{event_id}", result={
                    "history_id": history.id, "message": message.model_dump(mode="json"),
                })
                session.add(receipt)
                session.flush()
            history_id = receipt.result["history_id"]
            processed = session.scalar(select(InboxModel.id).where(InboxModel.id == event_id)) is not None
        if message.is_recent() and not processed:
            await self.inbound_queue.publish(message.model_copy(update={"history_id": history_id}))
