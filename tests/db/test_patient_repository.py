from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.patient_model import PatientModel
from app.repository.sql.patient_repository import PatientRepository


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


def test_exists_by_person_id_and_get_latest_by_person_id(
    patient_repository: PatientRepository,
    make_patient,
    make_person,
) -> None:
    person = make_person(phone_number="11911111112")
    older = make_patient(
        person=person,
        area="Nutrição",
        created_at=datetime(2026, 1, 1),
    )
    latest = make_patient(
        person=person,
        area="Psicoterapia",
        created_at=datetime(2026, 1, 2),
    )

    assert patient_repository.exists_by_person_id(person.id) is True
    found = patient_repository.get_latest_by_person_id(person.id)

    assert found is not None
    assert found.id == latest.id
    assert found.id != older.id
    assert found.area == "Psicoterapia"


def test_exists_by_person_id_returns_false_when_not_found(
    patient_repository: PatientRepository,
) -> None:
    assert patient_repository.exists_by_person_id(999999) is False
