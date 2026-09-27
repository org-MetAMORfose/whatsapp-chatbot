import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.db.delivery_model import OutboxModel
from app.domain.whatsapp.matching_patient_template import MatchingPatientTemplate
from app.repository.sql.matching_notification_repository import MatchingNotificationRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.matching_completed_relay import MatchingCompletedRelay


def dependencies(payload: dict[str, Any]) -> tuple[MatchingCompletedRelay, MagicMock, MagicMock, MagicMock, OutboxModel]:
    repo = MagicMock(spec=OutboxRepository)
    item = OutboxModel(id="event", kind="matching.completed", payload=payload, attempts=1)
    repo.claim.return_value = item
    notifications = MagicMock(spec=MatchingNotificationRepository)
    notifications.resolve.return_value = MatchingPatientTemplate("5511988887777", "Dra. Ana", "Psicoterapia", "5511977776666")
    adapter = MagicMock(spec=WhatsAppAdapter)
    adapter.send_template = AsyncMock(return_value="wamid.test")
    return MatchingCompletedRelay(repo, notifications, adapter), repo, notifications, adapter, item


@pytest.mark.asyncio
async def test_claim_only_completed_and_finish_after_send():
    relay, repo, notifications, adapter, item = dependencies({"status": "matched", "patient_id": 1, "slot_id": 2, "cycle_id": 3})
    entered, release = asyncio.Event(), asyncio.Event()

    async def send(**kwargs):
        entered.set()
        await release.wait()
        return "wamid.test"

    adapter.send_template.side_effect = send
    task = asyncio.create_task(relay.process_next())
    await asyncio.wait_for(entered.wait(), 5)
    repo.finish.assert_not_called()
    release.set()
    assert await task is True
    repo.claim.assert_called_once_with(kinds=("matching.completed",), max_attempts=5)
    notifications.resolve.assert_called_once_with(1, slot_id=2, cycle_id=3)
    adapter.send_template.assert_awaited_once_with(to="5511988887777", name="matching_paciente", language="pt_BR",
        body_parameters=("Dra. Ana", "Psicoterapia", "https://wa.me/5511977776666"))
    adapter.send_message.assert_not_called()
    repo.finish.assert_called_once_with(item, max_attempts=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["no_capacity", "patient_not_found"])
async def test_non_matched_statuses_are_consumed_without_sending(status):
    relay, repo, notifications, adapter, item = dependencies({"status": status, "patient_id": 1})
    assert await relay.process_next() is True
    adapter.send_template.assert_not_called()
    notifications.resolve.assert_not_called()
    repo.finish.assert_called_once_with(item, max_attempts=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"status": "unknown"}, {"status": "matched"},
    {"status": "matched", "patient_id": True}, {"status": "matched", "patient_id": 1, "slot_id": -1}])
async def test_invalid_event_is_processing_error(payload):
    relay, repo, _, adapter, item = dependencies(payload)
    await relay.process_next()
    adapter.send_template.assert_not_called()
    args, kwargs = repo.finish.call_args
    assert args[0] is item and isinstance(args[1], ValueError)
    assert kwargs == {"max_attempts": 5}


@pytest.mark.asyncio
async def test_missing_allocation_is_retryable_error():
    relay, repo, notifications, adapter, item = dependencies({"status": "matched", "patient_id": 1})
    error = ValueError("missing professional")
    notifications.resolve.side_effect = error
    await relay.process_next()
    adapter.send_template.assert_not_called()
    repo.finish.assert_called_once_with(item, error, max_attempts=5)


@pytest.mark.asyncio
async def test_http_failure_does_not_mark_sent():
    relay, repo, _, adapter, item = dependencies({"status": "matched", "patient_id": 1})
    error = TimeoutError("WhatsApp timeout")
    adapter.send_template.side_effect = error
    await relay.process_next()
    repo.finish.assert_called_once_with(item, error, max_attempts=5)


@pytest.mark.parametrize("values", [
    ("", "Ana", "Psicoterapia", "5511977776666"),
    ("5511988887777", " ", "Psicoterapia", "5511977776666"),
    ("5511988887777", "Ana", "", "5511977776666"),
    ("5511988887777", "Ana", "Psicoterapia", "not a phone"),
])
def test_template_rejects_missing_contact_data(values):
    with pytest.raises(ValueError):
        MatchingPatientTemplate(*values)
