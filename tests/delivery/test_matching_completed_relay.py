import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select, update

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.db.delivery_model import OutboxModel
from app.domain.db.matching_model import MatchingCycleModel, MatchingSlotModel
from app.domain.db.patient_model import PatientModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.repository.sql.matching_notification_repository import MatchingNotificationRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.matching_completed_relay import MatchingCompletedRelay


@pytest.fixture
def notification(factory):
    now = datetime.now(UTC)
    with factory() as db, db.begin():
        patient_person = PersonModel(phone_number="5511988887777", channel=Channel.WHATSAPP, name="Patient", created_at=now)
        professional_person = PersonModel(phone_number="+55 (11) 97777-6666", channel=Channel.WHATSAPP, name="Dra. Ana", created_at=now)
        db.add_all([patient_person, professional_person])
        db.flush()
        patient = PatientModel(person_id=patient_person.id, area="Psicoterapia", created_at=now)
        professional = ProfessionalModel(person_id=professional_person.id, area="Psicoterapia", professional_register="123",
                                         register_type="CRP", created_at=now)
        db.add_all([patient, professional])
        db.flush()
        cycle = MatchingCycleModel(professional_id=professional.id, type="REGULAR", promised_patients=1,
                                   starts_at=now, deadline_at=now+timedelta(days=10))
        db.add(cycle)
        db.flush()
        slot = MatchingSlotModel(patient_id=patient.id, cycle_id=cycle.id, compatibility_score=0, urgency_score=0,
                                 final_score=0, score_breakdown={}, algorithm_version="test")
        db.add(slot)
        db.flush()
        payload = {"status": "matched", "patient_id": patient.id, "cycle_id": cycle.id, "slot_id": slot.id}
        db.add(OutboxModel(id="notification", kind="matching.completed", payload=payload))
        db.add(OutboxModel(id="other-event", kind="matching.requested", payload={}))
    repo = OutboxRepository(factory)
    resolver = MatchingNotificationRepository(factory)
    adapter = MagicMock(spec=WhatsAppAdapter)
    adapter.send_template = AsyncMock(return_value="wamid.test")
    return MatchingCompletedRelay(repo, resolver, adapter), adapter, payload


@pytest.mark.asyncio
async def test_database_resolution_and_completed_event_not_sent_twice(factory, notification):
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
    second = MatchingCompletedRelay(OutboxRepository(factory), MatchingNotificationRepository(factory), adapter)
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


@pytest.mark.parametrize("field", ["slot_id", "cycle_id", "patient_id"])
def test_resolver_rejects_mismatched_identifiers(factory, notification, field):
    _, _, payload = notification
    params = {key: payload[key] for key in ("patient_id", "cycle_id", "slot_id")}
    params[field] += 999
    with pytest.raises(ValueError):
        MatchingNotificationRepository(factory).resolve(**params)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["phone_number", "name"])
async def test_incomplete_professional_contact_is_not_silently_sent(factory, notification, field):
    relay, adapter, _ = notification
    with factory() as db, db.begin():
        professional_person_id = db.scalar(select(ProfessionalModel.person_id))
        db.execute(update(PersonModel).where(PersonModel.id == professional_person_id).values(**{field: ""}))
    await relay.process_next()
    adapter.send_template.assert_not_called()
    with factory() as db:
        assert db.get(OutboxModel, "notification").status == "pending"
        assert db.get(OutboxModel, "notification").last_error == "ValueError"
