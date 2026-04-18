from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.patient_model import PatientModel
from app.repository.patient_repository import PatientRepository


@pytest.fixture
def patient_repository(
    session_factory: sessionmaker[Session],
) -> PatientRepository:
    return PatientRepository(session_factory)


def test_create(
    patient_repository: PatientRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11911111111")

    patient = PatientModel(
        person_id=person.id,
        created_at=datetime.utcnow(),
    )

    created = patient_repository.create(patient)

    assert created.id is not None
    assert created.person_id == person.id


def test_get_by_id(
    patient_repository: PatientRepository,
    make_patient,
) -> None:
    patient = make_patient()

    found = patient_repository.get_by_id(patient.id)

    assert found is not None
    assert found.id == patient.id
    assert found.person_id == patient.person_id


def test_get_by_id_returns_none_when_not_found(
    patient_repository: PatientRepository,
) -> None:
    found = patient_repository.get_by_id(999999)

    assert found is None


def test_get_by_person_id(
    patient_repository: PatientRepository,
    make_patient,
) -> None:
    patient = make_patient()

    found = patient_repository.get_by_person_id(patient.person_id)

    assert found is not None
    assert found.id == patient.id
    assert found.person_id == patient.person_id


def test_get_by_person_id_returns_none_when_not_found(
    patient_repository: PatientRepository,
) -> None:
    found = patient_repository.get_by_person_id(999999)

    assert found is None


def test_get_professionals_returns_empty_list_when_patient_has_no_links(
    patient_repository: PatientRepository,
    make_patient,
) -> None:
    patient = make_patient()

    professionals = patient_repository.get_professionals(patient.id)

    assert professionals == []


def test_get_professionals_returns_all_linked_professionals(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_professional_patient_link,
    make_person,
) -> None:
    patient = make_patient()

    professional_1 = make_professional(
        person=make_person(phone_number="11920000001"),
        professional_register="11111",
        email="prof1@test.com",
    )
    professional_2 = make_professional(
        person=make_person(phone_number="11920000002"),
        professional_register="22222",
        email="prof2@test.com",
    )

    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patient.id,
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patient.id,
    )

    professionals = patient_repository.get_professionals(patient.id)

    assert len(professionals) == 2
    professional_ids = {professional.id for professional in professionals}
    assert professional_ids == {professional_1.id, professional_2.id}


def test_link_professional(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_person,
) -> None:
    patient = make_patient()
    professional = make_professional(
        person=make_person(phone_number="11920000003"),
        professional_register="33333",
        email="prof3@test.com",
    )

    link = patient_repository.link_professional(
        patient_id=patient.id,
        professional_id=professional.id,
        created_at=datetime.utcnow(),
    )

    assert link.id is not None
    assert link.patient_id == patient.id
    assert link.professional_id == professional.id


def test_unlink_professional_returns_true_when_link_exists(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_professional_patient_link,
    make_person,
) -> None:
    patient = make_patient()
    professional = make_professional(
        person=make_person(phone_number="11920000004"),
        professional_register="44444",
        email="prof4@test.com",
    )

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient.id,
    )

    deleted = patient_repository.unlink_professional(
        patient_id=patient.id,
        professional_id=professional.id,
    )

    assert deleted is True
    assert (
        patient_repository.is_linked_to_professional(
            patient_id=patient.id,
            professional_id=professional.id,
        )
        is False
    )


def test_unlink_professional_returns_false_when_link_does_not_exist(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_person,
) -> None:
    patient = make_patient()
    professional = make_professional(
        person=make_person(phone_number="11920000005"),
        professional_register="55555",
        email="prof5@test.com",
    )

    deleted = patient_repository.unlink_professional(
        patient_id=patient.id,
        professional_id=professional.id,
    )

    assert deleted is False


def test_is_linked_to_professional_returns_true_when_link_exists(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_professional_patient_link,
    make_person,
) -> None:
    patient = make_patient()
    professional = make_professional(
        person=make_person(phone_number="11920000006"),
        professional_register="66666",
        email="prof6@test.com",
    )

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient.id,
    )

    assert (
        patient_repository.is_linked_to_professional(
            patient_id=patient.id,
            professional_id=professional.id,
        )
        is True
    )


def test_is_linked_to_professional_returns_false_when_link_does_not_exist(
    patient_repository: PatientRepository,
    make_patient,
    make_professional,
    make_person,
) -> None:
    patient = make_patient()
    professional = make_professional(
        person=make_person(phone_number="11920000007"),
        professional_register="77777",
        email="prof7@test.com",
    )

    assert (
        patient_repository.is_linked_to_professional(
            patient_id=patient.id,
            professional_id=professional.id,
        )
        is False
    )