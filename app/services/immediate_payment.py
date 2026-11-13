"""Shared "the Pix was paid" step used by the bank webhook and by the payment-timeout check."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository


def confirm_payment(
    requests: ImmediateRequestRepository,
    outbox: OutboxRepository,
    *,
    txid: str,
    e2e_id: str,
    paid_at: datetime,
    now: datetime,
    offer_timeout: timedelta,
) -> ImmediateRequestModel | None:
    """Queue the request and schedule the offer and its deadline; None when the payment was already handled.

    Must run inside a business transaction (`transaction(...)`), so the state change and the outbox rows commit together.
    The offer window starts when we learn about the payment, not when the bank booked it: a late webhook (or the
    30-minute bank check) must still give the psychologists their 5 minutes.
    """
    deadline = max(paid_at, now) + offer_timeout
    request = requests.mark_paid(txid, e2e_id=e2e_id, paid_at=paid_at, offer_deadline=deadline)
    if request is None:
        return None
    outbox.enqueue(f"immediate:{request.id}:offer", "immediate.offer.v1", {"request_id": request.id})
    outbox.enqueue(f"immediate:{request.id}:timeout", "immediate.timeout.v1", {"request_id": request.id}, available_at=deadline)
    return request
