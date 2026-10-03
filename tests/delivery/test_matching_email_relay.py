import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event
from unittest.mock import MagicMock

import pytest

from app.domain.db.delivery_model import OutboxModel
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.email_service import GmailSmtpAdapter
from app.services.matching_email_relay import MatchingEmailRelay


def payload() -> dict[str, object]:
    return {
        "status": "matched",
        "patient_id": 1,
        "slot_id": 2,
        "cycle_id": 3,
        "patient_name": "Leo",
        "patient_phone": "5511988887777",
        "patient_area": "Psicoterapia",
        "professional_email": "ana@example.com",
    }


@pytest.mark.asyncio
async def test_two_relays_do_not_send_the_same_active_email(factory) -> None:
    with factory() as db, db.begin():
        db.add(
            OutboxModel(
                id="matching:professional-email:event",
                kind="matching.professional.email",
                payload=payload(),
            )
        )

    adapter = MagicMock(spec=GmailSmtpAdapter)
    entered = Event()
    release = Event()

    def send(*args, **kwargs) -> None:
        entered.set()
        assert release.wait(5)

    adapter.send.side_effect = send
    first = MatchingEmailRelay(OutboxRepository(factory), adapter)
    second = MatchingEmailRelay(OutboxRepository(factory), adapter)

    task = asyncio.create_task(first.process_next())
    assert await asyncio.to_thread(entered.wait, 5)
    try:
        assert await second.process_next() is False
        with factory() as db:
            assert db.get(OutboxModel, "matching:professional-email:event").status == "processing"
    finally:
        release.set()
        await task

    adapter.send.assert_called_once()
    with factory() as db:
        assert db.get(OutboxModel, "matching:professional-email:event").status == "sent"


@pytest.mark.asyncio
async def test_smtp_failure_requeues_email(factory) -> None:
    with factory() as db, db.begin():
        db.add(
            OutboxModel(
                id="matching:professional-email:event",
                kind="matching.professional.email",
                payload=payload(),
            )
        )

    adapter = MagicMock(spec=GmailSmtpAdapter)
    adapter.send.side_effect = TimeoutError("SMTP timeout")
    relay = MatchingEmailRelay(OutboxRepository(factory), adapter)

    assert await relay.process_next() is True

    with factory() as db, db.begin():
        item = db.get(OutboxModel, "matching:professional-email:event")
        assert item.status == "pending"
        assert item.attempts == 1
        assert item.last_error == "TimeoutError"
        assert item.available_at > datetime.now(UTC) - timedelta(seconds=1)
