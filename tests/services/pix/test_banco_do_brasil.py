import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.pix import brcode
from app.services.pix.banco_do_brasil import BancoDoBrasilPixGateway

TXID = "a" * 32
BASE = "https://api-pix.hm.bb.com.br/pix/v2"
OAUTH = "https://oauth.hm.bb.com.br/oauth/token"


class Recorder:
    def __init__(self, responses: dict[str, httpx.Response | list[httpx.Response]]) -> None:
        self.responses = responses
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = f"{request.method} {request.url.path}"
        response = self.responses[key]
        if isinstance(response, list):
            return response.pop(0)
        return response


def token_response(expires_in: int = 600) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": expires_in})


def make_gateway(recorder: Recorder) -> BancoDoBrasilPixGateway:
    return BancoDoBrasilPixGateway(
        client_id="id",
        client_secret="secret",
        dev_app_key="devkey",
        cert_path="",
        key_path="",
        chave="chave@bb",
        base_url=BASE,
        oauth_url=OAUTH,
        transport=httpx.MockTransport(recorder),
    )


def cob_response(**extra: object) -> httpx.Response:
    body: dict[str, object] = {
        "txid": TXID,
        "status": "ATIVA",
        "location": "pix.bb.com.br/qr/v2/abc123",
        "calendario": {"criacao": "2026-11-12T20:00:00Z", "expiracao": 1800},
        **extra,
    }
    return httpx.Response(201, json=body)


@pytest.mark.asyncio
async def test_token_is_cached_until_expiry():
    recorder = Recorder(
        {"POST /oauth/token": [token_response(600), token_response(600)], f"PUT /pix/v2/cob/{TXID}": cob_response(pixCopiaECola="000201X")}
    )
    gateway = make_gateway(recorder)
    await gateway.create_charge(txid=TXID, amount_cents=6000, expires_seconds=1800, payer_name="Maria")
    await gateway.create_charge(txid=TXID, amount_cents=6000, expires_seconds=1800, payer_name="Maria")
    token_calls = [call for call in recorder.calls if call.url.path == "/oauth/token"]
    assert len(token_calls) == 1
    assert token_calls[0].headers["Authorization"].startswith("Basic ")
    form = parse_qs(token_calls[0].content.decode())
    assert form["grant_type"] == ["client_credentials"]
    assert "cob.write" in form["scope"][0] and "pix.write" in form["scope"][0]
    cob_calls = [call for call in recorder.calls if call.url.path.endswith(TXID)]
    assert all(call.headers["Authorization"] == "Bearer tok" for call in cob_calls)


@pytest.mark.asyncio
async def test_create_charge_uses_pixcopiaecola_when_present():
    recorder = Recorder({"POST /oauth/token": token_response(), f"PUT /pix/v2/cob/{TXID}": cob_response(pixCopiaECola="000201BB")})
    gateway = make_gateway(recorder)
    charge = await gateway.create_charge(txid=TXID, amount_cents=6000, expires_seconds=1800, payer_name="Maria")
    assert charge.txid == TXID
    assert charge.copia_cola == "000201BB"
    assert charge.expires_at == datetime(2026, 11, 12, 20, 30, tzinfo=UTC)
    put = next(call for call in recorder.calls if call.method == "PUT")
    assert put.url.params["gw-dev-app-key"] == "devkey"
    body = json.loads(put.content)
    assert body["calendario"] == {"expiracao": 1800}
    assert body["valor"] == {"original": "60.00"}
    assert body["chave"] == "chave@bb"
    assert "solicitacaoPagador" not in body  # would show "acolhimento" on the payer's bank statement


@pytest.mark.asyncio
async def test_create_charge_builds_brcode_from_location_when_absent():
    recorder = Recorder({"POST /oauth/token": token_response(), f"PUT /pix/v2/cob/{TXID}": cob_response()})
    gateway = make_gateway(recorder)
    charge = await gateway.create_charge(txid=TXID, amount_cents=6000, expires_seconds=1800, payer_name=None)
    assert charge.copia_cola == brcode.from_location(location="pix.bb.com.br/qr/v2/abc123", merchant_name="METAMORFOSE", merchant_city="SAO PAULO")


@pytest.mark.asyncio
async def test_get_charge_reads_payment_from_pix_list():
    payment = {"endToEndId": "E123", "horario": "2026-11-12T20:05:00.000Z", "valor": "60.00"}
    paid = httpx.Response(200, json={"txid": TXID, "status": "CONCLUIDA", "pix": [payment]})
    recorder = Recorder({"POST /oauth/token": token_response(), f"GET /pix/v2/cob/{TXID}": paid})
    status = await make_gateway(recorder).get_charge(TXID)
    assert status.txid == TXID and status.paid is True
    assert status.e2e_id == "E123"
    assert status.paid_at == datetime(2026, 11, 12, 20, 5, tzinfo=UTC)

    active = httpx.Response(200, json={"txid": TXID, "status": "ATIVA"})
    recorder = Recorder({"POST /oauth/token": token_response(), f"GET /pix/v2/cob/{TXID}": active})
    status = await make_gateway(recorder).get_charge(TXID)
    assert status.paid is False and status.e2e_id is None and status.paid_at is None


@pytest.mark.asyncio
async def test_refund_puts_devolucao_with_amount():
    response = httpx.Response(201, json={"id": TXID + "R1", "status": "EM_PROCESSAMENTO", "valor": "60.00"})
    recorder = Recorder({"POST /oauth/token": token_response(), f"PUT /pix/v2/pix/E123/devolucao/{TXID}R1": response})
    refund = await make_gateway(recorder).refund(e2e_id="E123", refund_id=TXID + "R1", amount_cents=6000)
    assert refund.refund_id == TXID + "R1" and refund.status == "EM_PROCESSAMENTO"
    put = next(call for call in recorder.calls if call.method == "PUT")
    assert json.loads(put.content) == {"valor": "60.00"}


@pytest.mark.asyncio
async def test_register_webhook_puts_url_for_key():
    recorder = Recorder({"POST /oauth/token": token_response(), "PUT /pix/v2/webhook/chave@bb": httpx.Response(204)})
    await make_gateway(recorder).register_webhook("https://chatbot.example.com/pix/webhook/segredo")
    put = next(call for call in recorder.calls if call.method == "PUT")
    assert json.loads(put.content) == {"webhookUrl": "https://chatbot.example.com/pix/webhook/segredo"}


@pytest.mark.asyncio
async def test_http_error_raises_without_the_app_key():
    from app.services.pix.banco_do_brasil import PixBankError

    recorder = Recorder({"POST /oauth/token": token_response(), f"PUT /pix/v2/cob/{TXID}": httpx.Response(500, json={"erro": "x"})})
    with pytest.raises(PixBankError) as error:
        await make_gateway(recorder).create_charge(txid=TXID, amount_cents=6000, expires_seconds=1800, payer_name=None)
    assert error.value.status_code == 500
    assert "devkey" not in str(error.value) and "gw-dev-app-key" not in str(error.value)


@pytest.mark.asyncio
async def test_get_refund_reads_status():
    response = httpx.Response(200, json={"id": TXID + "R1", "status": "DEVOLVIDO", "valor": "60.00"})
    recorder = Recorder({"POST /oauth/token": token_response(), f"GET /pix/v2/pix/E123/devolucao/{TXID}R1": response})
    refund = await make_gateway(recorder).get_refund(e2e_id="E123", refund_id=TXID + "R1")
    assert refund.refund_id == TXID + "R1" and refund.status == "DEVOLVIDO"


@pytest.mark.asyncio
async def test_cancel_charge_patches_cob_as_removed():
    removed = httpx.Response(200, json={"status": "REMOVIDA_PELO_USUARIO_RECEBEDOR"})
    recorder = Recorder({"POST /oauth/token": token_response(), f"PATCH /pix/v2/cob/{TXID}": removed})
    await make_gateway(recorder).cancel_charge(TXID)
    patch = next(call for call in recorder.calls if call.method == "PATCH")
    assert json.loads(patch.content) == {"status": "REMOVIDA_PELO_USUARIO_RECEBEDOR"}
