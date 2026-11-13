"""Immediate care requests against a real PostgreSQL (DELIVERY_TEST_DATABASE_URL)."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.enum.immediate_status import ImmediateStatus
from app.repository.sql.immediate_request_repository import ImmediateRequestRepository
from app.repository.sql.professional_repository import ProfessionalRepository

NOW = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
DEADLINE = NOW + timedelta(minutes=30)


def make_person(factory: Callable[[], Session], phone: str, name: str = "Maria") -> PersonModel:
    with factory() as session:
        person = PersonModel(phone_number=phone, channel=Channel.WHATSAPP, name=name, created_at=datetime.utcnow())
        session.add(person)
        session.commit()
        session.refresh(person)
        return person


def make_professional(factory: Callable[[], Session], person: PersonModel, *, area: str = "Psicoterapia") -> ProfessionalModel:
    with factory() as session:
        professional = ProfessionalModel(
            person_id=person.id, area=area, professional_register=f"CRP-{person.id}", register_type="CRP", created_at=datetime.utcnow()
        )
        session.add(professional)
        session.commit()
        session.refresh(professional)
        return professional


def create(repository: ImmediateRequestRepository, person: PersonModel, *, txid: str = "a" * 32, expires_at: datetime = DEADLINE):
    return repository.create(
        patient_person_id=person.id, duration_minutes=30, amount_cents=6000, pix_txid=txid, pix_copia_cola=f"PIX-{txid}", expires_at=expires_at
    )


@pytest.fixture
def repository(factory):
    return ImmediateRequestRepository(factory)


def test_create_sets_awaiting_payment_and_timestamps(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    assert request.id > 0
    assert request.status == ImmediateStatus.AWAITING_PAYMENT.value
    assert request.pix_txid == "a" * 32
    assert request.pix_copia_cola == "PIX-" + "a" * 32
    assert request.created_at is not None and request.updated_at is not None
    assert request.paid_at is None and request.professional_person_id is None
    assert repository.get(request.id) is not None
    assert repository.get_by_txid("a" * 32).id == request.id


def test_get_active_for_patient_ignores_expired_unpaid(factory, repository):
    person = make_person(factory, "5511900000001")
    create(repository, person, txid="b" * 32, expires_at=NOW - timedelta(minutes=1))
    assert repository.get_active_for_patient(person.id, now=NOW, room_grace_minutes=15) is None
    queued = create(repository, person, txid="c" * 32)
    repository.mark_paid("c" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    assert repository.get_active_for_patient(person.id, now=NOW, room_grace_minutes=15).id == queued.id


def test_mark_paid_transitions_once(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    deadline = NOW + timedelta(minutes=5)
    paid = repository.mark_paid("a" * 32, e2e_id="E123", paid_at=NOW, offer_deadline=deadline)
    assert paid is not None and paid.id == request.id
    assert paid.status == ImmediateStatus.QUEUED.value
    assert paid.pix_e2e_id == "E123" and paid.paid_at == NOW and paid.expires_at == deadline
    assert repository.mark_paid("a" * 32, e2e_id="E123", paid_at=NOW, offer_deadline=deadline) is None
    assert repository.mark_paid("z" * 32, e2e_id="E9", paid_at=NOW, offer_deadline=deadline) is None


def test_mark_paid_accepts_cancelled_request(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    assert repository.cancel(request.id) is True
    paid = repository.mark_paid("a" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    assert paid is not None and paid.status == ImmediateStatus.QUEUED.value


def test_accept_only_from_queued_before_deadline(factory, repository):
    patient = make_person(factory, "5511900000001")
    professional = make_person(factory, "5511900000002", name="Dra. Ana")
    request = create(repository, patient)
    assert repository.accept(request.id, professional_person_id=professional.id, now=NOW) is False
    repository.mark_paid("a" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    assert repository.accept(request.id, professional_person_id=professional.id, now=NOW + timedelta(minutes=6)) is False
    assert repository.accept(request.id, professional_person_id=professional.id, now=NOW + timedelta(minutes=1)) is True
    accepted = repository.get(request.id)
    assert accepted.status == ImmediateStatus.ACCEPTED.value
    assert accepted.professional_person_id == professional.id and accepted.accepted_at == NOW + timedelta(minutes=1)
    assert repository.accept(request.id, professional_person_id=professional.id, now=NOW + timedelta(minutes=1)) is False


def test_expire_cancel_set_refunded_are_idempotent(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    assert repository.expire(request.id) is False
    assert repository.cancel(request.id) is True
    assert repository.cancel(request.id) is False
    queued = create(repository, person, txid="d" * 32)
    repository.mark_paid("d" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    assert repository.expire(queued.id) is True
    assert repository.expire(queued.id) is False
    assert repository.set_refunded(queued.id, refund_id="d" * 32 + "R1", refunded_at=NOW) is True
    assert repository.set_refunded(queued.id, refund_id="d" * 32 + "R1", refunded_at=NOW) is False
    refunded = repository.get(queued.id)
    assert refunded.status == ImmediateStatus.EXPIRED.value and refunded.pix_refund_id == "d" * 32 + "R1"
    repository.set_room(queued.id, "https://exemplo.daily.co/sala")
    assert repository.get(queued.id).room_url == "https://exemplo.daily.co/sala"


def test_list_recent_newest_first(factory, repository):
    person = make_person(factory, "5511900000001")
    first = create(repository, person, txid="e" * 32)
    second = create(repository, person, txid="f" * 32)
    assert [request.id for request in repository.list_recent(limit=10)] == [second.id, first.id]
    assert [request.id for request in repository.list_recent(limit=1)] == [second.id]
    assert repository.list_recent(limit=10)[0].patient.phone_number == "5511900000001"


def test_professional_availability_toggle_and_listing(factory):
    professionals = ProfessionalRepository(factory)
    psychologist = make_professional(factory, make_person(factory, "5511900000002", name="Dra. Ana"))
    nutritionist = make_professional(factory, make_person(factory, "5511900000003"), area="Nutrição")
    assert psychologist.available_for_immediate is False
    assert professionals.list_available_for_immediate() == []
    updated = professionals.set_available_for_immediate(psychologist.person_id, True, now=NOW)
    assert updated is not None and updated.available_for_immediate is True and updated.immediate_availability_updated_at == NOW
    professionals.set_available_for_immediate(nutritionist.person_id, True, now=NOW)
    listed = professionals.list_available_for_immediate()
    assert [professional.person.phone_number for professional in listed] == ["5511900000002"]
    professionals.set_available_for_immediate(psychologist.person_id, False, now=NOW)
    assert professionals.list_available_for_immediate() == []
    assert professionals.set_available_for_immediate(999999, True, now=NOW) is None


def test_accept_is_atomic_under_concurrency(factory, repository):
    patient = make_person(factory, "5511900000001")
    candidates = [make_person(factory, f"551190000001{index}", name=f"Pro {index}") for index in range(8)]
    request = create(repository, patient)
    repository.mark_paid("a" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda person: repository.accept(request.id, professional_person_id=person.id, now=NOW), candidates))
    assert results.count(True) == 1
    winner = repository.get(request.id).professional_person_id
    assert winner in {person.id for person in candidates}


def test_set_refund_pending_stores_id_without_refunded_at(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    repository.set_refund_pending(request.id, refund_id="a" * 32 + "R1")
    stored = repository.get(request.id)
    assert stored.pix_refund_id == "a" * 32 + "R1" and stored.refunded_at is None
    assert repository.set_refunded(request.id, refund_id="a" * 32 + "R1", refunded_at=NOW) is True


def test_list_available_excludes_pending_review_and_accepts_legacy_areas(factory):
    professionals = ProfessionalRepository(factory)
    approved = make_professional(factory, make_person(factory, "5511900000002", name="Dra. Ana"))
    legacy = make_professional(factory, make_person(factory, "5511900000003", name="Dr. Bia"), area="Psicoterapia, Psiquiatria")
    analyst = make_professional(factory, make_person(factory, "5511900000004", name="Dr. Caio"), area="Psicanálise")
    pending = make_person(factory, "5511900000005", name="Pendente")
    with factory() as session:
        session.add(
            ProfessionalModel(
                person_id=pending.id, area="Psicoterapia", professional_register="CRP-9", register_type="PENDING_REVIEW", created_at=datetime.utcnow()
            )
        )
        session.commit()
    for person_id in (approved.person_id, legacy.person_id, analyst.person_id, pending.id):
        professionals.set_available_for_immediate(person_id, True, now=NOW)
    listed = professionals.list_available_for_immediate()
    assert [professional.person.phone_number for professional in listed] == ["5511900000002", "5511900000003", "5511900000004"]


def test_get_active_for_patient_releases_accepted_after_session_window(factory, repository):
    """An accepted session blocks a new request only while it can still be happening (duration + room grace)."""
    person = make_person(factory, "5511900000001")
    professional = make_person(factory, "5511900000009", name="Dra. Ana")
    request = create(repository, person, txid="d" * 32)
    repository.mark_paid("d" * 32, e2e_id="E1", paid_at=NOW, offer_deadline=NOW + timedelta(minutes=5))
    assert repository.accept(request.id, professional_person_id=professional.id, now=NOW) is True
    during = repository.get_active_for_patient(person.id, now=NOW + timedelta(minutes=44), room_grace_minutes=15)
    assert during is not None and during.id == request.id
    assert repository.get_active_for_patient(person.id, now=NOW + timedelta(minutes=46), room_grace_minutes=15) is None


def test_set_refund_failed_records_once(factory, repository):
    person = make_person(factory, "5511900000001")
    request = create(repository, person)
    assert repository.set_refund_failed(request.id, refund_id="a" * 32 + "R1", failed_at=NOW) is True
    stored = repository.get(request.id)
    assert stored.refund_failed_at is not None and stored.pix_refund_id == "a" * 32 + "R1" and stored.refunded_at is None
    assert repository.set_refund_failed(request.id, refund_id="a" * 32 + "R1", failed_at=NOW) is False
    assert repository.set_refunded(request.id, refund_id="a" * 32 + "R1", refunded_at=NOW) is True
