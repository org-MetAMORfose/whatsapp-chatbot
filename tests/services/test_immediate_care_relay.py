from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.domain.db.delivery_model import OutboxModel
from app.domain.db.immediate_request_model import ImmediateRequestModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.enum.immediate_status import ImmediateStatus
from app.domain.message import Message
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.services.immediate_care_relay import ImmediateCareRelay
from app.services.pix.gateway import PixChargeStatus, PixRefund

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
TXID = "a" * 32
PATIENT_PHONE = "5511999999999"
PRO_PHONE = "5511977776666"
ROOM = "https://exemplo.daily.co/sala"
REFUNDED_TEXT = "Pix de R$ 60,00 devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET."
REFUND_FAILED_TEXT = (
    "Não consegui devolver o seu Pix de R$ 60,00 automaticamente. A equipe da MetAMORfose vai fazer a devolução manualmente "
    "e te avisa por aqui."
)
PAYMENT_EXPIRED_TEXT = "O Pix expirou e nada foi cobrado. Se ainda quiser, mande RESET e peça de novo."


def patient() -> PersonModel:
    return PersonModel(id=7, phone_number=PATIENT_PHONE, channel=Channel.WHATSAPP, name="Maria Silva")


def professional_person(phone: str = PRO_PHONE, name: str = "Dra. Ana") -> PersonModel:
    return PersonModel(id=9, phone_number=phone, channel=Channel.WHATSAPP, name=name)


def available(phone: str = PRO_PHONE) -> ProfessionalModel:
    model = ProfessionalModel(id=3, person_id=9, area="Psicoterapia", professional_register="1", register_type="CRP", available_for_immediate=True)
    model.person = professional_person(phone)
    return model


def request(status: ImmediateStatus, **extra: object) -> ImmediateRequestModel:
    model = ImmediateRequestModel(
        id=42,
        patient_person_id=7,
        duration_minutes=30,
        amount_cents=6000,
        status=status.value,
        pix_txid=TXID,
        pix_copia_cola="PIX",
        pix_e2e_id="E123",
        expires_at=NOW + timedelta(minutes=5),
    )
    model.patient = patient()
    model.professional = None
    for key, value in extra.items():
        setattr(model, key, value)
    return model


def item(kind: str) -> OutboxModel:
    return OutboxModel(id=f"immediate:42:{kind.split('.')[1]}", kind=kind, payload={"request_id": 42}, attempts=1)


class Deps:
    def __init__(self, kind: str, current: ImmediateRequestModel | None, professionals: list[ProfessionalModel] | None = None) -> None:
        self.item = item(kind)
        self.outbox = MagicMock(spec=OutboxRepository)
        self.outbox.claim.return_value = self.item
        self.whatsapp = MagicMock(spec=WhatsAppAdapter)
        self.whatsapp.send_template = AsyncMock(return_value="wamid.1")
        self.outbound = MagicMock()
        self.outbound.publish = AsyncMock()
        self.requests = MagicMock(spec=ImmediateRequestRepository)
        self.requests.get.return_value = current
        self.professionals = MagicMock(spec=ProfessionalRepository)
        self.professionals.list_available_for_immediate.return_value = professionals or []
        self.people = MagicMock()
        self.people.get_or_create_person.return_value = professional_person()
        self.offers = MagicMock()
        self.offers.mark = AsyncMock()
        self.offers.clear = AsyncMock()
        self.chats = MagicMock()
        self.chats.create_context = AsyncMock()
        self.chats.delete_context = AsyncMock(return_value=True)
        self.chats.get_context = AsyncMock(return_value=SimpleNamespace(state="imediato_na_fila"))
        self.video = MagicMock()
        self.video.create_room = AsyncMock(return_value=ROOM)
        self.pix = MagicMock()
        self.pix.refund = AsyncMock(return_value=PixRefund(refund_id=TXID + "R1", status="DEVOLVIDO"))
        self.pix.get_refund = AsyncMock(return_value=PixRefund(refund_id=TXID + "R1", status="DEVOLVIDO"))
        self.pix.get_charge = AsyncMock(return_value=PixChargeStatus(txid=TXID, paid=False, e2e_id=None, paid_at=None))
        self.pix.cancel_charge = AsyncMock(return_value=None)
        self.relay = ImmediateCareRelay(
            self.outbox,
            self.whatsapp,
            self.outbound,
            self.requests,
            self.professionals,
            self.people,
            self.offers,
            self.chats,
            self.video,
            self.pix,
            MagicMock(),
            offer_timeout_seconds=300,
            room_grace_minutes=15,
            now=lambda: NOW,
        )

    def published(self) -> list[Message]:
        return [call.args[0] for call in self.outbound.publish.await_args_list]

    def finished_ok(self) -> bool:
        self.outbox.finish.assert_called_once()
        args, kwargs = self.outbox.finish.call_args
        return args[0] is self.item and len(args) == 1 and kwargs == {"max_attempts": ImmediateCareRelay.MAX_ATTEMPTS}

    def finished_with_error(self) -> bool:
        self.outbox.finish.assert_called_once()
        args, _kwargs = self.outbox.finish.call_args
        return args[0] is self.item and isinstance(args[1], Exception)


@pytest.mark.asyncio
async def test_claim_uses_all_kinds_and_returns_false_when_idle() -> None:
    deps = Deps("immediate.offer.v1", None)
    deps.outbox.claim.return_value = None
    assert await deps.relay.process_next() is False
    deps.outbox.claim.assert_called_once_with(kinds=ImmediateCareRelay.KINDS, max_attempts=ImmediateCareRelay.MAX_ATTEMPTS)
    assert ImmediateCareRelay.MAX_ATTEMPTS >= 100
    assert ImmediateCareRelay.KINDS == (
        "immediate.offer.v1",
        "immediate.timeout.v1",
        "immediate.refund.v1",
        "immediate.refund_check.v1",
        "immediate.accepted.v1",
        "immediate.payment_timeout.v1",
        "immediate.cancel_charge.v1",
    )


@pytest.mark.asyncio
async def test_offer_sends_template_to_each_available_and_moves_patient_to_queue_node() -> None:
    deps = Deps("immediate.offer.v1", request(ImmediateStatus.QUEUED), [available(), available("5511966665555")])
    assert await deps.relay.process_next() is True
    assert deps.whatsapp.send_template.await_count == 2
    for call, phone in zip(deps.whatsapp.send_template.await_args_list, [PRO_PHONE, "5511966665555"], strict=True):
        assert call.kwargs == {
            "to": phone,
            "name": "acolhimento_oferta",
            "language": "pt_BR",
            "body_parameters": ("Maria", "30", "60,00"),
            "callback_data": None,
        }
    assert [call.args for call in deps.offers.mark.await_args_list] == [(PRO_PHONE, Channel.WHATSAPP, 42), ("5511966665555", Channel.WHATSAPP, 42)]
    assert all(call.kwargs == {"ttl_seconds": 300} for call in deps.offers.mark.await_args_list)
    assert deps.people.create_message.call_count == 2
    recorded = deps.people.create_message.call_args.args[0]
    assert recorded.is_from_user is False and recorded.content.startswith("[template:acolhimento_oferta:pt_BR] Maria | 30 | 60,00")
    messages = deps.published()
    assert [(message.user_id, message.content) for message in messages] == [
        (PATIENT_PHONE, "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos.")
    ]
    assert messages[0].event_id == f"immediate:42:offer:{PATIENT_PHONE}" and messages[0].chat_id == PATIENT_PHONE
    deps.chats.create_context.assert_awaited_once_with(PATIENT_PHONE, Channel.WHATSAPP, "imediato_na_fila")
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_offer_with_no_available_professionals_still_waits() -> None:
    deps = Deps("immediate.offer.v1", request(ImmediateStatus.QUEUED), [])
    await deps.relay.process_next()
    deps.whatsapp.send_template.assert_not_awaited()
    assert [message.content for message in deps.published()] == [
        "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos."
    ]
    deps.chats.create_context.assert_awaited_once_with(PATIENT_PHONE, Channel.WHATSAPP, "imediato_na_fila")
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_offer_skips_when_not_queued() -> None:
    deps = Deps("immediate.offer.v1", request(ImmediateStatus.ACCEPTED), [available()])
    await deps.relay.process_next()
    deps.whatsapp.send_template.assert_not_awaited()
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_offer_continues_when_one_send_fails() -> None:
    deps = Deps("immediate.offer.v1", request(ImmediateStatus.QUEUED), [available(), available("5511966665555")])
    deps.whatsapp.send_template.side_effect = [RuntimeError("meta down"), "wamid.2"]
    await deps.relay.process_next()
    assert deps.whatsapp.send_template.await_count == 2
    assert [call.args[0] for call in deps.offers.mark.await_args_list] == ["5511966665555"]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_timeout_expires_enqueues_refund_and_notifies() -> None:
    deps = Deps("immediate.timeout.v1", request(ImmediateStatus.EXPIRED))  # what `get` sees right after `expire`
    deps.requests.expire.return_value = True
    await deps.relay.process_next()
    deps.requests.expire.assert_called_once_with(42)
    deps.outbox.enqueue.assert_called_once_with("immediate:42:refund", "immediate.refund.v1", {"request_id": 42})
    assert [message.content for message in deps.published()] == [
        "Nos últimos 5 minutos nenhum psicólogo ficou disponível. Vou devolver o seu Pix de R$ 60,00 automaticamente; "
        "você recebe a confirmação por aqui."
    ]
    deps.chats.delete_context.assert_awaited_once_with(PATIENT_PHONE, Channel.WHATSAPP)
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_timeout_noop_when_already_accepted() -> None:
    deps = Deps("immediate.timeout.v1", request(ImmediateStatus.ACCEPTED))
    deps.requests.expire.return_value = False
    await deps.relay.process_next()
    deps.outbox.enqueue.assert_not_called()
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_refund_not_performed_is_recorded_and_patient_is_told(caplog: pytest.LogCaptureFixture) -> None:
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED))
    deps.pix.refund.return_value = PixRefund(refund_id=TXID + "R1", status="NAO_REALIZADO")
    with caplog.at_level("ERROR"):
        await deps.relay.process_next()
    deps.requests.set_refunded.assert_not_called()
    deps.requests.set_refund_failed.assert_called_once_with(42, refund_id=TXID + "R1", failed_at=NOW)
    assert [message.content for message in deps.published()] == [REFUND_FAILED_TEXT]
    deps.outbox.enqueue.assert_not_called()
    assert deps.finished_ok()
    assert any("manual" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_refund_transport_error_retries() -> None:
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED))
    deps.pix.refund.side_effect = RuntimeError("bb down")
    deps.pix.get_refund.side_effect = RuntimeError("bb down")
    await deps.relay.process_next()
    deps.requests.set_refunded.assert_not_called()
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_with_error()


@pytest.mark.asyncio
async def test_refund_in_processing_schedules_check_without_telling_patient() -> None:
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED))
    deps.pix.refund.return_value = PixRefund(refund_id=TXID + "R1", status="EM_PROCESSAMENTO")
    await deps.relay.process_next()
    deps.requests.set_refund_pending.assert_called_once_with(42, refund_id=TXID + "R1")
    deps.requests.set_refunded.assert_not_called()
    deps.outbox.enqueue.assert_called_once_with(
        "immediate:42:refund_check:1", "immediate.refund_check.v1", {"request_id": 42, "attempt": 1}, available_at=NOW + timedelta(seconds=60)
    )
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


def refund_check_item(attempt: int) -> OutboxModel:
    return OutboxModel(
        id=f"immediate:42:refund_check:{attempt}", kind="immediate.refund_check.v1", payload={"request_id": 42, "attempt": attempt}, attempts=1
    )


@pytest.mark.asyncio
async def test_refund_check_confirms_and_notifies() -> None:
    deps = Deps("immediate.refund_check.v1", request(ImmediateStatus.EXPIRED, pix_refund_id=TXID + "R1"))
    deps.outbox.claim.return_value = deps.item = refund_check_item(1)
    deps.requests.set_refunded.return_value = True
    await deps.relay.process_next()
    deps.pix.get_refund.assert_awaited_once_with(e2e_id="E123", refund_id=TXID + "R1")
    deps.requests.set_refunded.assert_called_once_with(42, refund_id=TXID + "R1", refunded_at=NOW)
    assert [message.content for message in deps.published()] == [
        "Pix de R$ 60,00 devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET."
    ]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_refund_check_reschedules_while_processing() -> None:
    deps = Deps("immediate.refund_check.v1", request(ImmediateStatus.EXPIRED, pix_refund_id=TXID + "R1"))
    deps.outbox.claim.return_value = deps.item = refund_check_item(3)
    deps.pix.get_refund.return_value = PixRefund(refund_id=TXID + "R1", status="EM_PROCESSAMENTO")
    await deps.relay.process_next()
    deps.outbox.enqueue.assert_called_once_with(
        "immediate:42:refund_check:4", "immediate.refund_check.v1", {"request_id": 42, "attempt": 4}, available_at=NOW + timedelta(seconds=60)
    )
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_refund_check_gives_up_after_limit_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    deps = Deps("immediate.refund_check.v1", request(ImmediateStatus.EXPIRED, pix_refund_id=TXID + "R1"))
    deps.outbox.claim.return_value = deps.item = refund_check_item(ImmediateCareRelay.REFUND_CHECK_LIMIT)
    deps.pix.get_refund.return_value = PixRefund(refund_id=TXID + "R1", status="EM_PROCESSAMENTO")
    with caplog.at_level("ERROR"):
        await deps.relay.process_next()
    deps.outbox.enqueue.assert_not_called()
    deps.requests.set_refund_failed.assert_called_once_with(42, refund_id=TXID + "R1", failed_at=NOW)
    assert [message.content for message in deps.published()] == [REFUND_FAILED_TEXT]
    assert any("manual" in record.getMessage() for record in caplog.records)
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_payment_timeout_confirms_late_payment_with_bank() -> None:
    deps = Deps("immediate.payment_timeout.v1", request(ImmediateStatus.AWAITING_PAYMENT))
    deps.pix.get_charge.return_value = PixChargeStatus(txid=TXID, paid=True, e2e_id="E9", paid_at=NOW)
    deps.requests.mark_paid.return_value = request(ImmediateStatus.QUEUED)
    await deps.relay.process_next()
    deps.requests.cancel.assert_not_called()
    deps.requests.mark_paid.assert_called_once_with(TXID, e2e_id="E9", paid_at=NOW, offer_deadline=NOW + timedelta(seconds=300))
    assert [call.args[:2] for call in deps.outbox.enqueue.call_args_list] == [
        ("immediate:42:offer", "immediate.offer.v1"),
        ("immediate:42:timeout", "immediate.timeout.v1"),
    ]
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_offer_isolates_bad_professional_records() -> None:
    deps = Deps("immediate.offer.v1", request(ImmediateStatus.QUEUED), [available("0123"), available()])
    await deps.relay.process_next()
    deps.whatsapp.send_template.assert_awaited_once()
    assert deps.whatsapp.send_template.await_args.kwargs["to"] == PRO_PHONE
    assert [message.content for message in deps.published()] == [
        "Pagamento recebido! Estou avisando os psicólogos disponíveis. Te retorno em até 5 minutos."
    ]
    deps.chats.create_context.assert_awaited_once_with(PATIENT_PHONE, Channel.WHATSAPP, "imediato_na_fila")
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_timeout_resends_notice_when_already_expired() -> None:
    deps = Deps("immediate.timeout.v1", request(ImmediateStatus.EXPIRED))
    deps.requests.expire.return_value = False
    await deps.relay.process_next()
    deps.outbox.enqueue.assert_called_once_with("immediate:42:refund", "immediate.refund.v1", {"request_id": 42})
    notice = deps.published()[0].content
    assert len(deps.published()) == 1 and notice is not None and notice.startswith("Nos últimos 5 minutos")
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_room_name_is_unguessable() -> None:
    accepted = request(ImmediateStatus.ACCEPTED, professional_person_id=9)
    accepted.professional = professional_person()
    deps = Deps("immediate.accepted.v1", accepted)
    await deps.relay.process_next()
    name = deps.video.create_room.await_args.kwargs["name"]
    assert name.startswith("acolhimento-42-") and len(name.removeprefix("acolhimento-42-")) >= 22


@pytest.mark.asyncio
async def test_last_attempt_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    deps = Deps("immediate.weird.v1", request(ImmediateStatus.QUEUED))
    deps.item.attempts = ImmediateCareRelay.MAX_ATTEMPTS
    with caplog.at_level("ERROR"):
        await deps.relay.process_next()
    assert any("exhausted" in record.getMessage() for record in caplog.records)
    assert deps.finished_with_error()


@pytest.mark.asyncio
async def test_refund_is_idempotent_but_resends_the_confirmation() -> None:
    """A retry after a crash between `set_refunded` and the message must not swallow the confirmation (event_id dedups)."""
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED, refunded_at=NOW, pix_refund_id=TXID + "R1"))
    await deps.relay.process_next()
    deps.pix.refund.assert_not_awaited()
    deps.requests.set_refunded.assert_not_called()
    assert [message.content for message in deps.published()] == [REFUNDED_TEXT]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_refund_success_marks_and_notifies() -> None:
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED))
    deps.requests.set_refunded.return_value = True
    await deps.relay.process_next()
    deps.pix.refund.assert_awaited_once_with(e2e_id="E123", refund_id=TXID + "R1", amount_cents=6000)
    deps.requests.set_refunded.assert_called_once_with(42, refund_id=TXID + "R1", refunded_at=NOW)
    assert [message.content for message in deps.published()] == [
        "Pix de R$ 60,00 devolvido. Pode levar alguns minutos pra aparecer no seu banco. Quando quiser tentar de novo, mande RESET."
    ]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_accepted_creates_room_once_and_notifies_both() -> None:
    accepted = request(ImmediateStatus.ACCEPTED, professional_person_id=9, accepted_at=NOW)
    accepted.professional = professional_person()
    deps = Deps("immediate.accepted.v1", accepted)
    await deps.relay.process_next()
    deps.video.create_room.assert_awaited_once()
    room_kwargs = deps.video.create_room.await_args.kwargs
    assert room_kwargs["name"].startswith("acolhimento-42-") and room_kwargs["expires_at"] == NOW + timedelta(minutes=45)
    deps.requests.set_room.assert_called_once_with(42, ROOM)
    assert [(message.user_id, message.content) for message in deps.published()] == [
        (PATIENT_PHONE, f"Um psicólogo aceitou o seu atendimento! Entre na sala de vídeo: {ROOM}\n\nA sessão dura 30 minutos e não é gravada."),
        (PRO_PHONE, f"Sala de vídeo do acolhimento: {ROOM}\n\nO paciente é Maria, sessão de 30 minutos."),
    ]
    deps.chats.delete_context.assert_not_awaited()  # the patient stays in the queue node and can ask for the link again
    deps.offers.clear.assert_awaited_once_with(PRO_PHONE, Channel.WHATSAPP)
    assert deps.finished_ok()

    again = Deps("immediate.accepted.v1", request(ImmediateStatus.ACCEPTED, professional_person_id=9, room_url=ROOM))
    again.requests.get.return_value.professional = professional_person()
    await again.relay.process_next()
    again.video.create_room.assert_not_awaited()
    again.requests.set_room.assert_not_called()
    assert len(again.published()) == 2
    assert again.finished_ok()


@pytest.mark.asyncio
async def test_accepted_without_professional_fails_for_retry() -> None:
    deps = Deps("immediate.accepted.v1", request(ImmediateStatus.ACCEPTED))
    await deps.relay.process_next()
    deps.video.create_room.assert_not_awaited()
    assert deps.finished_with_error()


@pytest.mark.asyncio
async def test_payment_timeout_cancels_and_notifies() -> None:
    deps = Deps("immediate.payment_timeout.v1", request(ImmediateStatus.AWAITING_PAYMENT))
    deps.requests.get.side_effect = [request(ImmediateStatus.AWAITING_PAYMENT), request(ImmediateStatus.CANCELLED)]
    deps.requests.cancel.return_value = True
    await deps.relay.process_next()
    deps.requests.cancel.assert_called_once_with(42)
    deps.pix.cancel_charge.assert_awaited_once_with(TXID)
    assert [message.content for message in deps.published()] == ["O Pix expirou e nada foi cobrado. Se ainda quiser, mande RESET e peça de novo."]
    deps.chats.delete_context.assert_awaited_once_with(PATIENT_PHONE, Channel.WHATSAPP)
    assert deps.finished_ok()

    paid = Deps("immediate.payment_timeout.v1", request(ImmediateStatus.QUEUED))
    paid.requests.cancel.return_value = False
    await paid.relay.process_next()
    paid.outbound.publish.assert_not_awaited()
    assert paid.finished_ok()


@pytest.mark.asyncio
async def test_unknown_kind_is_finished_with_error() -> None:
    deps = Deps("immediate.weird.v1", request(ImmediateStatus.QUEUED))
    await deps.relay.process_next()
    assert deps.finished_with_error()


@pytest.mark.asyncio
async def test_missing_request_is_finished_without_retry() -> None:
    deps = Deps("immediate.offer.v1", None)
    await deps.relay.process_next()
    deps.outbound.publish.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_payment_timeout_stays_quiet_after_the_patient_cancelled() -> None:
    """CANCELAR before paying must not be followed, 30 minutes later, by \"O Pix expirou\" and a wiped conversation."""
    cancelled = request(ImmediateStatus.CANCELLED, expires_at=NOW, updated_at=NOW - timedelta(minutes=10))
    deps = Deps("immediate.payment_timeout.v1", cancelled)
    await deps.relay.process_next()
    deps.requests.cancel.assert_not_called()
    deps.pix.get_charge.assert_not_awaited()
    deps.outbound.publish.assert_not_awaited()
    deps.chats.delete_context.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_payment_timeout_resends_the_notice_when_a_previous_attempt_cancelled() -> None:
    cancelled_by_deadline = request(ImmediateStatus.CANCELLED, expires_at=NOW - timedelta(minutes=1), updated_at=NOW - timedelta(seconds=30))
    deps = Deps("immediate.payment_timeout.v1", cancelled_by_deadline)
    await deps.relay.process_next()
    deps.requests.cancel.assert_not_called()
    assert [message.content for message in deps.published()] == [PAYMENT_EXPIRED_TEXT]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_timeout_leaves_a_patient_who_moved_to_another_flow_alone() -> None:
    deps = Deps("immediate.timeout.v1", request(ImmediateStatus.EXPIRED))
    deps.requests.expire.return_value = True
    deps.chats.get_context.return_value = SimpleNamespace(state="paciente_nome")
    await deps.relay.process_next()
    assert len(deps.published()) == 1
    deps.chats.delete_context.assert_not_awaited()
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_cancel_charge_removes_the_charge_only_while_cancelled() -> None:
    deps = Deps("immediate.cancel_charge.v1", request(ImmediateStatus.CANCELLED))
    await deps.relay.process_next()
    deps.pix.cancel_charge.assert_awaited_once_with(TXID)
    assert deps.finished_ok()

    paid_meanwhile = Deps("immediate.cancel_charge.v1", request(ImmediateStatus.QUEUED))
    await paid_meanwhile.relay.process_next()
    paid_meanwhile.pix.cancel_charge.assert_not_awaited()
    assert paid_meanwhile.finished_ok()


@pytest.mark.asyncio
async def test_refund_falls_back_to_querying_the_bank_when_the_put_fails() -> None:
    deps = Deps("immediate.refund.v1", request(ImmediateStatus.EXPIRED))
    deps.pix.refund.side_effect = RuntimeError("409 devolução já existe")
    deps.requests.set_refunded.return_value = True
    await deps.relay.process_next()
    deps.pix.get_refund.assert_awaited_once_with(e2e_id="E123", refund_id=TXID + "R1")
    deps.requests.set_refunded.assert_called_once_with(42, refund_id=TXID + "R1", refunded_at=NOW)
    assert [message.content for message in deps.published()] == [REFUNDED_TEXT]
    assert deps.finished_ok()


@pytest.mark.asyncio
async def test_late_payment_found_by_the_bank_gets_a_fresh_offer_window() -> None:
    deps = Deps("immediate.payment_timeout.v1", request(ImmediateStatus.AWAITING_PAYMENT))
    deps.pix.get_charge.return_value = PixChargeStatus(txid=TXID, paid=True, e2e_id="E9", paid_at=NOW - timedelta(minutes=30))
    deps.requests.mark_paid.return_value = request(ImmediateStatus.QUEUED)
    await deps.relay.process_next()
    deps.requests.mark_paid.assert_called_once_with(
        TXID, e2e_id="E9", paid_at=NOW - timedelta(minutes=30), offer_deadline=NOW + timedelta(seconds=300)
    )
    assert deps.finished_ok()
