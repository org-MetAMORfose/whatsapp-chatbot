import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.pix_webhook_controller import PixWebhookController, WebhookTokenLogFilter
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.services.pix.banco_do_brasil import PixBankError
from app.services.pix.gateway import PixChargeStatus

TXID = "a" * 32
TOKEN = "segredo"
PAID_AT = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
EVENT = {"txid": TXID, "endToEndId": "E123", "valor": "60.00", "horario": "2026-11-12T20:00:00Z", "infoPagador": "ignorado"}


def _client(requests: MagicMock, outbox: MagicMock, *, token: str = TOKEN, timeout: int = 300, verify=None, now=None) -> TestClient:
    app = FastAPI()
    controller = PixWebhookController(
        MagicMock(), requests, outbox, token=token, offer_timeout_seconds=timeout, verify_with_bank=verify, now=now or (lambda: PAID_AT)
    )
    app.include_router(controller.router)
    return TestClient(app)


def queued_request(**extra: object) -> ImmediateRequestModel:
    request = ImmediateRequestModel(
        id=42, patient_person_id=7, duration_minutes=30, amount_cents=6000, status="queued", pix_txid=TXID, expires_at=PAID_AT
    )
    for key, value in extra.items():
        setattr(request, key, value)
    return request


def known_requests(request: ImmediateRequestModel | None = None) -> MagicMock:
    requests = MagicMock()
    requests.get_by_txid.return_value = request if request is not None else queued_request(status="awaiting_payment")
    requests.mark_paid.return_value = queued_request()
    return requests


def test_wrong_token_is_404() -> None:
    requests, outbox = known_requests(), MagicMock()
    assert _client(requests, outbox).post("/pix/webhook/errado", json={"pix": [EVENT]}).status_code == 404
    assert _client(requests, outbox, token="").post("/pix/webhook/segredo", json={"pix": [EVENT]}).status_code == 404
    assert _client(requests, outbox).post("/pix/webhook/segr%C3%A9do", json={"pix": [EVENT]}).status_code == 404  # non-ASCII: still 404
    requests.mark_paid.assert_not_called()


def test_paid_event_queues_offer_and_timeout() -> None:
    requests, outbox = known_requests(), MagicMock()
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.status_code == 200
    assert response.json() == {"received": 1, "queued": 1}
    deadline = PAID_AT + timedelta(seconds=300)
    requests.mark_paid.assert_called_once_with(TXID, e2e_id="E123", paid_at=PAID_AT, offer_deadline=deadline)
    assert outbox.enqueue.call_args_list == [
        call("immediate:42:offer", "immediate.offer.v1", {"request_id": 42}),
        call("immediate:42:timeout", "immediate.timeout.v1", {"request_id": 42}, available_at=deadline),
    ]


def test_late_event_counts_the_offer_window_from_now() -> None:
    """A payment the bank reports late still gets its 5 minutes; otherwise the request would expire on arrival."""
    requests, outbox = known_requests(), MagicMock()
    now = PAID_AT + timedelta(minutes=10)
    _client(requests, outbox, now=lambda: now).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    requests.mark_paid.assert_called_once_with(TXID, e2e_id="E123", paid_at=PAID_AT, offer_deadline=now + timedelta(seconds=300))


def test_duplicate_event_queues_once() -> None:
    requests, outbox = known_requests(), MagicMock()
    requests.mark_paid.side_effect = [queued_request(), None]
    client = _client(requests, outbox)
    assert client.post("/pix/webhook/segredo", json={"pix": [EVENT]}).json() == {"received": 1, "queued": 1}
    assert client.post("/pix/webhook/segredo", json={"pix": [EVENT]}).json() == {"received": 1, "queued": 0}
    assert outbox.enqueue.call_count == 2


def test_unknown_txid_is_ignored() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.get_by_txid.return_value = None
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [{**EVENT, "txid": "z" * 32}]})
    assert response.status_code == 200 and response.json() == {"received": 1, "queued": 0}
    requests.mark_paid.assert_not_called()
    outbox.enqueue.assert_not_called()


def test_amount_mismatch_is_ignored() -> None:
    requests, outbox = known_requests(), MagicMock()
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [{**EVENT, "valor": "1.00"}]})
    assert response.json() == {"received": 1, "queued": 0}
    requests.mark_paid.assert_not_called()
    outbox.enqueue.assert_not_called()


def test_bank_verification_blocks_an_unpaid_charge_and_uses_the_bank_data() -> None:
    requests, outbox = known_requests(), MagicMock()
    verify = AsyncMock(return_value=PixChargeStatus(txid=TXID, paid=False, e2e_id=None, paid_at=None))
    response = _client(requests, outbox, verify=verify).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.json() == {"received": 1, "queued": 0}
    verify.assert_awaited_once_with(TXID)
    requests.mark_paid.assert_not_called()

    bank_paid_at = PAID_AT - timedelta(minutes=1)
    verify = AsyncMock(return_value=PixChargeStatus(txid=TXID, paid=True, e2e_id="E-banco", paid_at=bank_paid_at))
    requests = known_requests()
    response = _client(requests, outbox, verify=verify).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.json() == {"received": 1, "queued": 1}
    requests.mark_paid.assert_called_once_with(TXID, e2e_id="E-banco", paid_at=bank_paid_at, offer_deadline=PAID_AT + timedelta(seconds=300))


def test_bank_outage_during_verification_answers_with_an_error_so_the_bank_sends_the_event_again() -> None:
    """The BB test environment answered 504 once (2026-11-17): an outage must not mark the Pix as paid nor drop the event."""
    requests, outbox = known_requests(), MagicMock()
    verify = AsyncMock(side_effect=PixBankError("GET", "/cob/" + TXID, 504))
    app = FastAPI()
    controller = PixWebhookController(
        MagicMock(), requests, outbox, token=TOKEN, offer_timeout_seconds=300, verify_with_bank=verify, now=lambda: PAID_AT
    )
    app.include_router(controller.router)
    response = TestClient(app, raise_server_exceptions=False).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.status_code == 500
    requests.mark_paid.assert_not_called()
    outbox.enqueue.assert_not_called()


def test_late_payment_is_treated_like_any_payment() -> None:
    """Status handling lives in the repository (cancelled -> queued); the webhook never filters events by status."""
    requests, outbox = known_requests(queued_request(status="cancelled")), MagicMock()
    response = _client(requests, outbox).post("/pix/webhook/segredo", json={"pix": [EVENT]})
    assert response.json() == {"received": 1, "queued": 1}
    assert outbox.enqueue.call_count == 2


def test_bb_validation_path_with_pix_suffix_is_accepted() -> None:
    requests, outbox = MagicMock(), MagicMock()
    requests.get_by_txid.return_value = None
    client = _client(requests, outbox)
    assert client.post("/pix/webhook/segredo/pix", json={"pix": [EVENT]}).status_code == 200
    assert client.post("/pix/webhook/segredo/pix", json={"pix": []}).json() == {"received": 0, "queued": 0}


def test_invalid_body_is_422() -> None:
    client = _client(known_requests(), MagicMock())
    assert client.post("/pix/webhook/segredo", json={"pix": [{"txid": TXID}]}).status_code == 422
    assert client.post("/pix/webhook/segredo", json={"evento": "x"}).status_code == 422


def test_access_log_filter_masks_the_token() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "POST", "/pix/webhook/segredo/pix", "1.1", 200), None
    )
    assert WebhookTokenLogFilter().filter(record) is True
    assert record.getMessage() == '1.2.3.4:5 - "POST /pix/webhook/***/pix HTTP/1.1" 200'
    plain = logging.LogRecord("x", logging.INFO, __file__, 1, "Webhook registrado: https://h/pix/webhook/segredo", None, None)
    WebhookTokenLogFilter().filter(plain)
    assert plain.getMessage() == "Webhook registrado: https://h/pix/webhook/***"
