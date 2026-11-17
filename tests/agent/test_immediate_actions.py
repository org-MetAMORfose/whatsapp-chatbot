from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.config.settings as settings
from app.agent.action_executor import ActionExecutor, ActionResult
from app.agent.chat_flow import TransitionAction
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.enum.immediate_status import ImmediateStatus
from app.domain.message import Message
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.services.pix.gateway import PixCharge

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
CHARGE = PixCharge(txid="t" * 32, copia_cola="PIX-SIMULADO-CODIGO", expires_at=NOW + timedelta(minutes=30))


def make_message(content: str | None) -> Message:
    return Message(message_id=1, channel=Channel.WHATSAPP, created_at=NOW, user_id="5511999999999", chat_id="chat-1", content=content)


def make_request(status: ImmediateStatus, **extra: object) -> ImmediateRequestModel:
    request = ImmediateRequestModel(
        id=42,
        patient_person_id=7,
        duration_minutes=30,
        amount_cents=6000,
        status=status.value,
        pix_txid="t" * 32,
        pix_copia_cola="PIX-SIMULADO-CODIGO",
        expires_at=NOW + timedelta(minutes=30),
    )
    for key, value in extra.items():
        setattr(request, key, value)
    return request


def make_executor(*, with_immediate: bool = True) -> tuple[ActionExecutor, MagicMock, MagicMock, MagicMock]:
    person_repository = MagicMock()
    person_repository.get_by_phone_number_and_channel.return_value = PersonModel(
        id=7, name="Maria Silva", phone_number="5511999999999", channel=Channel.WHATSAPP
    )
    outbox_repository = MagicMock()
    requests = MagicMock(spec=ImmediateRequestRepository)
    requests.get_active_for_patient.return_value = None
    requests.create.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    gateway = MagicMock()
    gateway.create_charge = AsyncMock(return_value=CHARGE)
    gateway.cancel_charge = AsyncMock(return_value=None)
    professional_repository = MagicMock()
    professional_repository.list_available_for_immediate.return_value = [eligible_psychologist()]
    base = (MagicMock(), professional_repository, person_repository, MagicMock(), MagicMock(), outbox_repository, MagicMock())
    if with_immediate:
        executor = ActionExecutor(*base, immediate_requests=requests, pix_gateway=gateway, now=lambda: NOW)
    else:
        executor = ActionExecutor(*base)
    return executor, requests, gateway, outbox_repository


async def run(executor: ActionExecutor, key: str, content: str | None) -> ActionResult:
    return await executor.run([TransitionAction(action_key=key, is_required=True)], make_message(content))


PRICES = {10: 3000, 20: 5000, 40: 10000, 60: 15000}


@pytest.fixture(autouse=True)
def immediate_care_enabled(monkeypatch):
    monkeypatch.setattr(settings, "IMMEDIATE_PRICES_CENTS", dict(PRICES))
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", True)  # Pix and room are mocks here
    monkeypatch.setattr(settings, "IMMEDIATE_ROOM_GRACE_MINUTES", 15)


@pytest.mark.asyncio
async def test_create_request_refuses_when_active():
    executor, requests, gateway, outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.QUEUED)
    result = await run(executor, "immediate_create_request", "30 minutos")
    assert result.output == "" and result.data == {"immediate_active": True}
    gateway.create_charge.assert_not_awaited()
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_create_request_creates_charge_and_schedules_payment_timeout(monkeypatch):
    monkeypatch.setattr(settings, "IMMEDIATE_PAYMENT_TIMEOUT_SECONDS", 1800)
    executor, requests, gateway, outbox = make_executor()
    requests.create.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT, duration_minutes=20, amount_cents=5000)
    result = await run(executor, "immediate_create_request", "20 minutos")
    gateway.create_charge.assert_awaited_once()
    charge_kwargs = gateway.create_charge.await_args.kwargs
    assert len(charge_kwargs["txid"]) == 32 and charge_kwargs["txid"].isalnum()
    assert charge_kwargs["amount_cents"] == 5000 and charge_kwargs["expires_seconds"] == 1800 and charge_kwargs["payer_name"] == "Maria Silva"
    requests.create.assert_called_once_with(
        patient_person_id=7,
        duration_minutes=20,
        amount_cents=5000,
        pix_txid=charge_kwargs["txid"],
        pix_copia_cola="PIX-SIMULADO-CODIGO",
        expires_at=CHARGE.expires_at,
    )
    outbox.enqueue.assert_called_once_with(
        "immediate:42:payment_timeout", "immediate.payment_timeout.v1", {"request_id": 42}, available_at=CHARGE.expires_at
    )
    assert result.output == "Valor: R$ 50,00\n\nPix copia e cola:\nPIX-SIMULADO-CODIGO\n\n"
    assert result.data == {"immediate_active": False, "immediate_nobody_available": False, "immediate_request_id": 42}
    requests.get_active_for_patient.assert_called_once_with(7, now=NOW, room_grace_minutes=15)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minutes", "cents", "shown"), [(10, 3000, "R$ 30,00"), (20, 5000, "R$ 50,00"), (40, 10000, "R$ 100,00"), (60, 15000, "R$ 150,00")]
)
async def test_create_request_charges_the_price_of_the_chosen_duration(minutes, cents, shown):
    executor, requests, gateway, _outbox = make_executor()
    requests.create.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT, duration_minutes=minutes, amount_cents=cents)
    result = await run(executor, "immediate_create_request", f"{minutes} minutos")
    assert gateway.create_charge.await_args.kwargs["amount_cents"] == cents
    assert requests.create.call_args.kwargs["duration_minutes"] == minutes
    assert requests.create.call_args.kwargs["amount_cents"] == cents
    assert result.output.startswith(f"Valor: {shown}\n")


@pytest.mark.asyncio
async def test_a_price_changed_in_the_settings_is_what_gets_charged(monkeypatch):
    monkeypatch.setattr(settings, "IMMEDIATE_PRICES_CENTS", {**PRICES, 20: 5550})
    executor, _requests, gateway, _outbox = make_executor()
    await run(executor, "immediate_create_request", "20 minutos")
    assert gateway.create_charge.await_args.kwargs["amount_cents"] == 5550


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["uma hora", "30 minutos"])
async def test_a_duration_without_a_price_goes_to_the_failure_node_without_charging(content, caplog):
    """A flow button left without a price in IMMEDIATE_PRICES must not charge a guessed value."""
    executor, requests, gateway, outbox = make_executor()
    result = await run(executor, "immediate_create_request", content)
    assert result.output == ""
    assert result.data == {"immediate_active": False, "immediate_nobody_available": False, "immediate_pix_failed": True}
    gateway.create_charge.assert_not_awaited()
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()
    assert any("IMMEDIATE_PRICES" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_payment_status_awaiting_shows_code():
    executor, requests, _gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    result = await run(executor, "immediate_payment_status", "oi")
    assert result.output == "Ainda não recebi o pagamento. Pix copia e cola:\nPIX-SIMULADO-CODIGO\n\n"
    assert result.data == {"immediate_paid": False, "immediate_done": False}


@pytest.mark.asyncio
async def test_payment_status_queued():
    executor, requests, _gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.QUEUED)
    result = await run(executor, "immediate_payment_status", "oi")
    assert result.output == "Pagamento recebido!\n\n"
    assert result.data == {"immediate_paid": True, "immediate_done": False}


@pytest.mark.asyncio
async def test_payment_status_accepted_with_and_without_room():
    executor, requests, _gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.ACCEPTED, room_url="https://exemplo.daily.co/sala", patient_room_url="https://exemplo.daily.co/sala?t=paciente")
    result = await run(executor, "immediate_payment_status", "oi")
    assert result.output == "Seu atendimento já foi aceito. Sala de vídeo: https://exemplo.daily.co/sala?t=paciente\n\n"
    assert result.data == {"immediate_paid": True, "immediate_done": True}
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.ACCEPTED)
    result = await run(executor, "immediate_payment_status", "oi")
    assert result.output == "Seu atendimento já foi aceito. Estou criando a sala de vídeo.\n\n"


@pytest.mark.asyncio
async def test_payment_status_without_request():
    executor, _requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_payment_status", "oi")
    assert result.output == "Não encontrei um pedido em aberto.\n\n"
    assert result.data == {"immediate_paid": False, "immediate_done": True}


@pytest.mark.asyncio
async def test_cancel_only_awaiting():
    executor, requests, _gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.QUEUED)
    assert (await run(executor, "immediate_cancel", "cancelar")).data == {"immediate_paid": True}
    requests.cancel.assert_not_called()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    assert (await run(executor, "immediate_cancel", "cancelar")).output == ""
    requests.cancel.assert_called_once_with(42)


@pytest.mark.asyncio
async def test_executor_runs_without_immediate_dependencies():
    executor, _requests, _gateway, _outbox = make_executor(with_immediate=False)
    with pytest.raises(RuntimeError, match="Immediate care is not configured"):
        await run(executor, "immediate_create_request", "30 minutos")


def eligible_psychologist() -> ProfessionalModel:
    return ProfessionalModel(id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="CRP", available_for_immediate=True)


@pytest.mark.asyncio
async def test_create_request_refuses_when_nobody_available():
    executor, requests, gateway, outbox = make_executor()
    executor.professional_repository.list_available_for_immediate.return_value = []
    result = await run(executor, "immediate_create_request", "30 minutos")
    assert result.data == {"immediate_active": False, "immediate_nobody_available": True}
    assert result.output == ""
    gateway.create_charge.assert_not_awaited()
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_create_request_reports_availability_in_data():
    executor, _requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_create_request", "20 minutos")
    assert result.data == {"immediate_active": False, "immediate_nobody_available": False, "immediate_request_id": 42}


@pytest.mark.asyncio
async def test_cancel_paid_explains_and_keeps_waiting():
    executor, requests, gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.QUEUED)
    result = await run(executor, "immediate_cancel", "cancelar")
    assert result.output == "Seu pagamento já foi recebido, então o pedido não pode mais ser cancelado.\n\n"
    assert result.data == {"immediate_paid": True}
    requests.cancel.assert_not_called()
    gateway.cancel_charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_unpaid_schedules_charge_removal_outside_the_transaction():
    """The bank call must not run while the message transaction holds the row lock (it froze the worker)."""
    executor, requests, gateway, outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    requests.cancel.return_value = True
    result = await run(executor, "immediate_cancel", "cancelar")
    assert result.output == "" and result.data == {"immediate_paid": False}
    requests.cancel.assert_called_once_with(42)
    gateway.cancel_charge.assert_not_awaited()
    outbox.enqueue.assert_called_once_with("immediate:42:cancel_charge", "immediate.cancel_charge.v1", {"request_id": 42})


@pytest.mark.asyncio
async def test_cancel_losing_the_race_with_the_payment_reports_paid():
    executor, requests, _gateway, outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    requests.cancel.return_value = False  # the webhook moved it to queued a moment earlier
    result = await run(executor, "immediate_cancel", "cancelar")
    assert result.output == "Seu pagamento já foi recebido, então o pedido não pode mais ser cancelado.\n\n"
    assert result.data == {"immediate_paid": True}
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_without_request_is_done():
    executor, requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_cancel", "cancelar")
    assert result.output == "Não encontrei um pedido em aberto.\n\n"
    assert result.data == {"immediate_paid": False, "immediate_done": True}
    requests.cancel.assert_not_called()


@pytest.mark.asyncio
async def test_gate_follows_the_feature_flag(monkeypatch):
    executor, _requests, _gateway, _outbox = make_executor()
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", False)
    assert (await run(executor, "immediate_gate", "Atendimento imediato")).data == {"immediate_disabled": True}
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    assert (await run(executor, "immediate_gate", "Atendimento imediato")).data == {"immediate_disabled": False}


@pytest.mark.asyncio
async def test_gate_stays_closed_when_the_switch_is_on_but_production_config_is_missing(monkeypatch):
    executor, _requests, _gateway, _outbox = make_executor()
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", False)
    monkeypatch.setattr(settings, "PIX_PROVIDER", "fake")
    assert (await run(executor, "immediate_gate", "Atendimento imediato")).data == {"immediate_disabled": True}


@pytest.mark.asyncio
async def test_prices_are_shown_before_the_duration_choice():
    executor, _requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_prices", "Aceito os termos")
    assert result.output == (
        "Valores: 10 minutos por R$ 30,00, 20 minutos por R$ 50,00, 40 minutos por R$ 100,00 ou 60 minutos por R$ 150,00.\n\n"
    )


@pytest.mark.asyncio
async def test_a_single_price_is_shown_in_the_singular(monkeypatch):
    monkeypatch.setattr(settings, "IMMEDIATE_PRICES_CENTS", {30: 6000})
    executor, _requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_prices", "Aceito os termos")
    assert result.output == "Valor: 30 minutos por R$ 60,00.\n\n"


@pytest.mark.asyncio
async def test_noop_action_returns_empty_result():
    executor, _requests, _gateway, _outbox = make_executor()
    result = await run(executor, "immediate_noop", "30 minutos")
    assert result.output == "" and not result.data


@pytest.mark.asyncio
async def test_create_request_refuses_when_flag_is_off(monkeypatch):
    """A patient already past the menu gate must not be charged after the feature is switched off."""
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", False)
    executor, requests, gateway, outbox = make_executor()
    result = await run(executor, "immediate_create_request", "30 minutos")
    assert result.output == "" and result.data == {"immediate_disabled": True, "immediate_active": False}
    gateway.create_charge.assert_not_awaited()
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_create_request_with_open_pix_shows_the_existing_code():
    executor, requests, gateway, outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.AWAITING_PAYMENT)
    result = await run(executor, "immediate_create_request", "50 minutos")
    assert result.output == "Você já tem um Pix em aberto de R$ 60,00 (30 minutos).\n\nPix copia e cola:\nPIX-SIMULADO-CODIGO\n\n"
    assert result.data == {"immediate_active": False, "immediate_nobody_available": False}
    gateway.create_charge.assert_not_awaited()
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_create_request_with_accepted_session_shows_the_room():
    executor, requests, gateway, _outbox = make_executor()
    requests.get_active_for_patient.return_value = make_request(ImmediateStatus.ACCEPTED, room_url="https://exemplo.daily.co/sala", patient_room_url="https://exemplo.daily.co/sala?t=paciente")
    result = await run(executor, "immediate_create_request", "30 minutos")
    assert result.output == "Seu atendimento já foi aceito. Sala de vídeo: https://exemplo.daily.co/sala?t=paciente\n\n"
    assert result.data == {"immediate_active": True}
    gateway.create_charge.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_request_bank_failure_routes_to_the_failure_node():
    executor, requests, gateway, outbox = make_executor()
    gateway.create_charge.side_effect = RuntimeError("bb down")
    result = await run(executor, "immediate_create_request", "20 minutos")
    assert result.output == ""
    assert result.data == {"immediate_active": False, "immediate_nobody_available": False, "immediate_pix_failed": True}
    requests.create.assert_not_called()
    outbox.enqueue.assert_not_called()
