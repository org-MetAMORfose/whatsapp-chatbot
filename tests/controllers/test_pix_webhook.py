from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, call

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.pix_webhook_controller import PixWebhookController
from app.domain.db.immediate_request_model import ImmediateRequestModel

TXID = "a" * 32
TOKEN = "segredo"
PAID_AT = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
EVENT = {"txid": TXID, "endToEndId": "E123", "valor": "60.00", "horario": "2026-11-12T20:00:00Z", "infoPagador": "ignorado"}


def _client(requests: MagicMock, outbox: MagicMock, *, token: str = TOKEN, timeout: int = 300) -> TestClient:
    app = FastAPI()
    app.include_router(PixWebhookController(MagicMock(), requests, outbox, token=token, offer_timeout_seconds=timeout).router)
    return TestClient(app)


def queued_request() -> ImmediateRequestModel:
    return ImmediateRequestModel(
        id=42, patient_person_id=7, duration_minutes=30, amount_cents=6000, status="queued", pix_txid=TXID, expires_at=PAID_AT
    )


def test_wrong_token_is_404() -> None:
    requests, outbox = MagicMock(), MagicMock()
    assert _client(requests, outbox).post("/pix/webhook/errado", json={"pix": [EVENT]}).status_code == 404
    assert _client(requests, outbox, token="").post("/pix/webhook/segredo", json={"pix": [EVENT]}).status_code == 404
    requests.mark_paid.assert_not_called()


def test_paid_event_queues_offer_and_timeout() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.mark_paid.return_value = queued_request()
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.status_code == 200
    assert response.json() == {"received": 1, "queued": 1}
    deadline = PAID_AT + timedelta(seconds=300)
    requests.mark_paid.assert_called_once_with(TXID, e2e_id="E123", paid_at=PAID_AT, offer_deadline=deadline)
    assert outbox.enqueue.call_args_list == [
        call("immediate:42:offer", "immediate.offer.v1", {"request_id": 42}),
        call("immediate:42:timeout", "immediate.timeout.v1", {"request_id": 42}, available_at=deadline),
    ]


def test_duplicate_event_queues_once() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.mark_paid.side_effect = [queued_request(), None]
    client = _client(requests, outbox)
    assert client.post("/pix/webhook/segredo", json={"pix": [EVENT]}).json() == {"received": 1, "queued": 1}
    assert client.post("/pix/webhook/segredo", json={"pix": [EVENT]}).json() == {"received": 1, "queued": 0}
    assert outbox.enqueue.call_count == 2


def test_unknown_txid_is_ignored() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.mark_paid.return_value = None
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [{**EVENT, "txid": "z" * 32}]})
    assert response.status_code == 200 and response.json() == {"received": 1, "queued": 0}
    outbox.enqueue.assert_not_called()


def test_late_payment_is_treated_like_any_payment() -> None:
    """Status handling lives in the repository (cancelled -> queued); the webhook never filters events by status."""
    requests, outbox = MagicMock(), MagicMock()
    late = queued_request()
    requests.mark_paid.return_value = late
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.json() == {"received": 1, "queued": 1}
    assert outbox.enqueue.call_count == 2


def test_bb_validation_path_with_pix_suffix_is_accepted() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.mark_paid.return_value = None
    client = _client(requests, outbox)
    assert client.post("/pix/webhook/segredo/pix", json={"pix": [EVENT]}).status_code == 200
    assert client.post("/pix/webhook/segredo/pix", json={"pix": []}).json() == {"received": 0, "queued": 0}


def test_invalid_body_is_422() -> None:
    client = _client(MagicMock(), MagicMock())
    assert client.post("/pix/webhook/segredo", json={"pix": [{"txid": TXID}]}).status_code == 422
    assert client.post("/pix/webhook/segredo", json={"evento": "x"}).status_code == 422
