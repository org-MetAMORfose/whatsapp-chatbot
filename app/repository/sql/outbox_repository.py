"""Reserve and finalize integration deliveries using short SQL transactions."""
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.domain.db.delivery_model import OutboxModel
from app.repository.sql.transaction import current_session


class OutboxRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.factory = session_factory

    def enqueue(self, operation_id: str, kind: str, payload: dict[str, Any], available_at: datetime | None = None) -> None:
        session = current_session()
        if session.get(OutboxModel, operation_id) is None:
            session.add(OutboxModel(id=operation_id, kind=kind, payload=payload,
                                    available_at=available_at or datetime.now(UTC)))
            session.flush()

    def claim(self) -> OutboxModel | None:
        now = datetime.now(UTC)
        with self.factory() as session, session.begin():
            item = session.scalar(select(OutboxModel).where(or_(
                and_(OutboxModel.status == "pending", OutboxModel.available_at <= now),
                and_(OutboxModel.status == "processing", OutboxModel.locked_until <= now),
            )).order_by(OutboxModel.available_at, OutboxModel.id).limit(1).with_for_update(skip_locked=True))
            if item is None:
                return None
            item.status = "processing"
            item.attempts += 1
            item.locked_until = now + timedelta(minutes=5)
            session.flush()
            session.expunge(item)
            return item

    def finish(self, item: OutboxModel, error: Exception | None = None) -> None:
        values: dict[str, Any] = {"locked_until": None, "last_error": None, "status": "sent"}
        if error is not None:
            values.update(status="failed" if item.attempts >= 5 else "pending",
                          last_error=type(error).__name__,
                          available_at=datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** (item.attempts - 1))))
        with self.factory() as session, session.begin():
            session.execute(update(OutboxModel).where(
                OutboxModel.id == item.id, OutboxModel.status == "processing", OutboxModel.attempts == item.attempts,
            ).values(**values))

    def cleanup(self) -> None:
        with self.factory() as session, session.begin():
            session.execute(delete(OutboxModel).where(
                OutboxModel.status == "sent", OutboxModel.created_at < datetime.now(UTC) - timedelta(days=30),
            ))
