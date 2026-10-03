from typing import Any
from unittest.mock import MagicMock

import pytest

from app.domain.db.delivery_model import OutboxModel
from app.repository.sql.outbox_repository import OutboxRepository
from app.services.email_service import GmailSmtpAdapter, MatchingProfessionalEmail
from app.services.matching_email_relay import MatchingEmailRelay


def matched_payload() -> dict[str, Any]:
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


def dependencies(
    payload: dict[str, Any],
) -> tuple[MatchingEmailRelay, MagicMock, MagicMock, OutboxModel]:
    repository = MagicMock(spec=OutboxRepository)
    item = OutboxModel(
        id="matching:professional-email:event",
        kind="matching.professional.email",
        payload=payload,
        attempts=1,
    )
    repository.claim.return_value = item
    adapter = MagicMock(spec=GmailSmtpAdapter)
    return MatchingEmailRelay(repository, adapter), repository, adapter, item


@pytest.mark.asyncio
async def test_claims_only_email_and_marks_sent_after_smtp_acceptance() -> None:
    relay, repository, adapter, item = dependencies(matched_payload())

    assert await relay.process_next() is True

    repository.claim.assert_called_once_with(
        kinds=("matching.professional.email",),
        max_attempts=5,
    )
    adapter.send.assert_called_once_with(
        MatchingProfessionalEmail(
            recipient="ana@example.com",
            patient_name="Leo",
            patient_area="Psicoterapia",
            patient_phone="5511988887777",
        ),
        operation_id=item.id,
    )
    repository.finish.assert_called_once_with(item, max_attempts=5)


@pytest.mark.asyncio
async def test_smtp_failure_is_retried_and_not_marked_sent() -> None:
    relay, repository, adapter, item = dependencies(matched_payload())
    error = TimeoutError("SMTP timeout")
    adapter.send.side_effect = error

    assert await relay.process_next() is True

    repository.finish.assert_called_once_with(item, error, max_attempts=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    ["professional_email", "patient_name", "patient_area", "patient_phone"],
)
async def test_incomplete_snapshot_is_a_retryable_error(field: str) -> None:
    payload = matched_payload()
    payload[field] = ""
    relay, repository, adapter, item = dependencies(payload)

    assert await relay.process_next() is True

    adapter.send.assert_not_called()
    args, kwargs = repository.finish.call_args
    assert args[0] is item
    assert isinstance(args[1], ValueError)
    assert kwargs == {"max_attempts": 5}


@pytest.mark.asyncio
async def test_ignores_queue_when_no_email_is_ready() -> None:
    relay, repository, adapter, _ = dependencies(matched_payload())
    repository.claim.return_value = None

    assert await relay.process_next() is False

    adapter.send.assert_not_called()
    repository.finish.assert_not_called()
