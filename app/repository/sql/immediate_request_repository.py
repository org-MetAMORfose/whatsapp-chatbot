"""Immediate care requests: every state transition is one conditional UPDATE, so concurrent workers never double-apply it."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.domain.db.delivery_model import utcnow
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.enum.immediate_status import ImmediateStatus
from app.repository.sql.transaction import commit, session_scope

AWAITING = ImmediateStatus.AWAITING_PAYMENT.value
QUEUED = ImmediateStatus.QUEUED.value
ACCEPTED = ImmediateStatus.ACCEPTED.value
EXPIRED = ImmediateStatus.EXPIRED.value
CANCELLED = ImmediateStatus.CANCELLED.value


class ImmediateRequestRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(
        self,
        *,
        patient_person_id: int,
        duration_minutes: int,
        amount_cents: int,
        pix_txid: str,
        pix_copia_cola: str,
        expires_at: datetime,
    ) -> ImmediateRequestModel:
        request = ImmediateRequestModel(
            patient_person_id=patient_person_id,
            duration_minutes=duration_minutes,
            amount_cents=amount_cents,
            status=AWAITING,
            pix_txid=pix_txid,
            pix_copia_cola=pix_copia_cola,
            expires_at=expires_at,
        )
        with session_scope(self._session_factory) as session:
            session.add(request)
            commit(session)
            session.refresh(request)
            return request

    def get(self, request_id: int) -> ImmediateRequestModel | None:
        with session_scope(self._session_factory) as session:
            return session.get(ImmediateRequestModel, request_id)

    def get_by_txid(self, txid: str) -> ImmediateRequestModel | None:
        with session_scope(self._session_factory) as session:
            return session.scalar(select(ImmediateRequestModel).where(ImmediateRequestModel.pix_txid == txid))

    def get_active_for_patient(self, patient_person_id: int, *, now: datetime) -> ImmediateRequestModel | None:
        """Latest request still worth waiting for: queued/accepted, or unpaid within its payment deadline."""
        with session_scope(self._session_factory) as session:
            stmt = (
                select(ImmediateRequestModel)
                .where(
                    ImmediateRequestModel.patient_person_id == patient_person_id,
                    or_(
                        ImmediateRequestModel.status.in_((QUEUED, ACCEPTED)),
                        and_(ImmediateRequestModel.status == AWAITING, ImmediateRequestModel.expires_at > now),
                    ),
                )
                .order_by(ImmediateRequestModel.created_at.desc(), ImmediateRequestModel.id.desc())
                .limit(1)
            )
            return session.scalar(stmt)

    def mark_paid(self, txid: str, *, e2e_id: str, paid_at: datetime, offer_deadline: datetime) -> ImmediateRequestModel | None:
        """Move an unpaid (or cancelled-for-late-payment) request to the queue; None when nothing changed."""
        with session_scope(self._session_factory) as session:
            stmt = (
                update(ImmediateRequestModel)
                .where(ImmediateRequestModel.pix_txid == txid, ImmediateRequestModel.status.in_((AWAITING, CANCELLED)))
                .values(status=QUEUED, pix_e2e_id=e2e_id, paid_at=paid_at, expires_at=offer_deadline, updated_at=utcnow())
                .returning(ImmediateRequestModel.id)
            )
            request_id = session.execute(stmt).scalar_one_or_none()
            if request_id is None:
                return None
            commit(session)
            return session.get(ImmediateRequestModel, request_id)

    def accept(self, request_id: int, *, professional_person_id: int, now: datetime) -> bool:
        return self._transition(
            request_id,
            where=and_(ImmediateRequestModel.status == QUEUED, ImmediateRequestModel.expires_at > now),
            values={"status": ACCEPTED, "professional_person_id": professional_person_id, "accepted_at": now},
        )

    def expire(self, request_id: int) -> bool:
        return self._transition(request_id, where=ImmediateRequestModel.status == QUEUED, values={"status": EXPIRED})

    def cancel(self, request_id: int) -> bool:
        return self._transition(request_id, where=ImmediateRequestModel.status == AWAITING, values={"status": CANCELLED})

    def set_room(self, request_id: int, room_url: str) -> None:
        self._transition(request_id, where=ImmediateRequestModel.id == request_id, values={"room_url": room_url})

    def set_refund_pending(self, request_id: int, *, refund_id: str) -> None:
        """Remember the refund the bank is still processing; `refunded_at` stays empty until it confirms."""
        self._transition(request_id, where=ImmediateRequestModel.refunded_at.is_(None), values={"pix_refund_id": refund_id})

    def set_refunded(self, request_id: int, *, refund_id: str, refunded_at: datetime) -> bool:
        return self._transition(
            request_id,
            where=ImmediateRequestModel.refunded_at.is_(None),
            values={"pix_refund_id": refund_id, "refunded_at": refunded_at},
        )

    def list_recent(self, limit: int = 100) -> list[ImmediateRequestModel]:
        with session_scope(self._session_factory) as session:
            stmt = (
                select(ImmediateRequestModel)
                .order_by(ImmediateRequestModel.created_at.desc(), ImmediateRequestModel.id.desc())
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    def _transition(self, request_id: int, *, where: object, values: dict[str, object]) -> bool:
        with session_scope(self._session_factory) as session:
            stmt = (
                update(ImmediateRequestModel)
                .where(ImmediateRequestModel.id == request_id, where)  # type: ignore[arg-type]
                .values(updated_at=utcnow(), **values)
            )
            result = cast(CursorResult[Any], session.execute(stmt))
            changed = result.rowcount == 1
            commit(session)
            return changed
