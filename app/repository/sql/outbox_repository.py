"""Reserve and finalize integration deliveries using short SQL transactions."""

from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, or_, select, true, update
from sqlalchemy.orm import Session

from app.domain.db.delivery_model import OutboxModel
from app.repository.sql.transaction import current_session


class OutboxRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.factory = session_factory

    def enqueue(self, operation_id: str, kind: str, payload: dict[str, Any], available_at: datetime | None = None) -> None:
        session = current_session()
        if session.get(OutboxModel, operation_id) is None:
            session.add(OutboxModel(id=operation_id, kind=kind, payload=payload, available_at=available_at or datetime.now(UTC)))
            session.flush()

    def claim(self, *, kinds: Collection[str] | None = None, max_attempts: int = 5) -> OutboxModel | None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = datetime.now(UTC)
        with self.factory() as session, session.begin():
            item = session.scalar(
                select(OutboxModel)
                .where(
                    OutboxModel.kind.in_(kinds) if kinds is not None else true(),
                    or_(
                        and_(OutboxModel.status == "pending", OutboxModel.available_at <= now),
                        and_(OutboxModel.status == "processing", OutboxModel.locked_until <= now),
                    ),
                )
                .order_by(OutboxModel.available_at, OutboxModel.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if item is None:
                return None
            if item.attempts >= max_attempts:
                item.status = "failed"
                item.locked_until = None
                item.last_error = "Delivery attempts exhausted"
                return None
            item.status = "processing"
            item.attempts += 1
            item.locked_until = now + timedelta(minutes=5)
            session.flush()
            session.expunge(item)
            return item

    def finish(self, item: OutboxModel, error: Exception | None = None, *, max_attempts: int = 5) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        values: dict[str, Any] = {"locked_until": None, "last_error": None, "status": "sent"}
        if error is not None:
            values.update(
                status="failed" if item.attempts >= max_attempts else "pending",
                last_error=type(error).__name__,
                available_at=datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** (item.attempts - 1))),
            )
        with self.factory() as session, session.begin():
            session.execute(
                update(OutboxModel)
                .where(
                    OutboxModel.id == item.id,
                    OutboxModel.status == "processing",
                    OutboxModel.attempts == item.attempts,
                )
                .values(**values)
            )

    def await_whatsapp_delivery(
        self,
        item: OutboxModel,
        *,
        timeout: timedelta = timedelta(hours=1),
    ) -> bool:
        """Keep an accepted template leased until its webhook receipt arrives."""
        if timeout <= timedelta(0):
            raise ValueError("WhatsApp delivery timeout must be positive")
        with self.factory() as session, session.begin():
            current = session.scalar(
                select(OutboxModel)
                .where(
                    OutboxModel.id == item.id,
                    OutboxModel.status == "processing",
                    OutboxModel.attempts == item.attempts,
                )
                .with_for_update()
            )
            if current is None:
                return False
            current.locked_until = datetime.now(UTC) + timeout
            current.last_error = None
            return True

    def finish_whatsapp_delivery(
        self,
        operation_id: str,
        attempt: int,
        delivery_status: str,
        error: str | None = None,
        *,
        max_attempts: int = 5,
    ) -> bool:
        """Finalize a template intent from an asynchronous WhatsApp receipt."""
        if delivery_status not in {"sent", "delivered", "read", "failed"}:
            return False
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = datetime.now(UTC)
        with self.factory() as session, session.begin():
            item = session.scalar(
                select(OutboxModel)
                .where(
                    OutboxModel.id == operation_id,
                    OutboxModel.kind.in_(
                        {
                            "matching.completed",
                            "matching.professional.notification",
                        }
                    ),
                    OutboxModel.status == "processing",
                    OutboxModel.attempts == attempt,
                )
                .with_for_update()
            )
            if item is None:
                return False
            item.locked_until = None
            if delivery_status == "failed":
                item.status = "failed" if item.attempts >= max_attempts else "pending"
                item.last_error = (error or "WhatsApp delivery failed")[:2000]
                item.available_at = now + timedelta(seconds=min(300, 5 * 2 ** (item.attempts - 1)))
            else:
                item.status = "sent"
                item.last_error = None
            return True

    def cleanup(self) -> None:
        with self.factory() as session, session.begin():
            session.execute(
                delete(OutboxModel).where(
                    OutboxModel.status == "sent",
                    OutboxModel.created_at < datetime.now(UTC) - timedelta(days=30),
                )
            )
