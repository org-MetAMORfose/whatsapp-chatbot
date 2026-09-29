import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.db.delivery_model import OutboxModel
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.matching_completed_relay import MatchingCompletedRelay


@pytest.fixture
def notification(factory):
    # No patient, person, professional, slot or cycle exists in this database.
    # Only the durable snapshot is needed to send the notification.
    with factory() as db, db.begin():
        payload = {"status": "matched", "patient_id": 1, "cycle_id": 2, "slot_id": 3,
                   "patient_phone": "5511988887777", "professional_name": "Dra. Ana",
                   "professional_area": "Psicoterapia", "professional_phone": "+55 (11) 97777-6666"}
        db.add(OutboxModel(id="notification", kind="matching.completed", payload=payload))
        db.add(OutboxModel(id="other-event", kind="matching.requested", payload={}))
    repo = OutboxRepository(factory)
    adapter = MagicMock(spec=WhatsAppAdapter)
    adapter.send_template = AsyncMock(return_value="wamid.test")
    return MatchingCompletedRelay(repo, adapter), adapter, payload


@pytest.mark.asyncio
async def test_snapshot_without_business_records_and_completed_event_not_sent_twice(factory, notification):
    relay, adapter, _ = notification
    assert await relay.process_next()
    adapter.send_template.assert_awaited_once_with(to="5511988887777", name="matching_paciente", language="pt_BR",
        body_parameters=("Dra. Ana", "Psicoterapia", "https://wa.me/5511977776666"))
    assert not await relay.process_next()
    with factory() as db:
        assert db.get(OutboxModel, "notification").status == "sent"
        assert db.get(OutboxModel, "other-event").status == "pending"


@pytest.mark.asyncio
async def test_two_relays_do_not_send_same_active_event(factory, notification):
    first, adapter, _ = notification
    second = MatchingCompletedRelay(OutboxRepository(factory), adapter)
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(**kwargs):
        entered.set()
        await release.wait()
        return "wamid.test"

    adapter.send_template.side_effect = send
    task = asyncio.create_task(first.process_next())
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert not await second.process_next()
    finally:
        release.set()
        await task
    adapter.send_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_send_is_retried_then_completed(factory, notification):
    relay, adapter, _ = notification
    adapter.send_template.side_effect = TimeoutError()
    await relay.process_next()
    with factory() as db, db.begin():
        item = db.get(OutboxModel, "notification")
        assert item.status == "pending" and item.attempts == 1 and item.locked_until is None
        assert item.last_error == "TimeoutError"
        item.available_at = datetime.now(UTC)-timedelta(seconds=1)
    adapter.send_template.side_effect = None
    await relay.process_next()
    with factory() as db:
        assert db.get(OutboxModel, "notification").status == "sent"
        assert db.get(OutboxModel, "notification").attempts == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["patient_phone", "professional_name", "professional_area", "professional_phone"])
async def test_incomplete_professional_contact_is_not_silently_sent(factory, notification, field):
    relay, adapter, _ = notification
    with factory() as db, db.begin():
        item = db.get(OutboxModel, "notification")
        item.payload = {**item.payload, field: ""}
    await relay.process_next()
    adapter.send_template.assert_not_called()
    with factory() as db:
        assert db.get(OutboxModel, "notification").status == "pending"
        assert db.get(OutboxModel, "notification").last_error == "ValueError"


@pytest.mark.asyncio
async def test_professional_notification_has_independent_delivery(factory):
    payload = {
        "status": "matched",
        "patient_id": 1,
        "cycle_id": 2,
        "slot_id": 3,
        "patient_name": "Leo",
        "patient_phone": "5511988887777",
        "patient_area": "Psicoterapia",
        "professional_name": "Dra. Ana",
        "professional_area": "Psicoterapia",
        "professional_phone": "5511977776666",
    }
    with factory() as db, db.begin():
        db.add(OutboxModel(
            id="professional-notification",
            kind="matching.professional.notification",
            payload=payload,
        ))
    repo = OutboxRepository(factory)
    adapter = MagicMock(spec=WhatsAppAdapter)
    adapter.send_template = AsyncMock(return_value="wamid.professional")
    relay = MatchingCompletedRelay(repo, adapter)

    assert await relay.process_next()
    adapter.send_template.assert_awaited_once_with(
        to="5511977776666",
        name="matching_professional",
        language="pt_BR",
        body_parameters=("Leo", "Psicoterapia", "https://wa.me/5511988887777"),
    )
    with factory() as db:
        assert db.get(OutboxModel, "professional-notification").status == "sent"
