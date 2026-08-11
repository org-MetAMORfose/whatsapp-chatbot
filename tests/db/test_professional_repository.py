from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repository.sql.professional_repository import ProfessionalRepository


@pytest.fixture
def professional_repository(
    session_factory: sessionmaker[Session],
) -> ProfessionalRepository:
    return ProfessionalRepository(session_factory)


def test_get_by_id(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000002"),
        professional_register="10002",
        email="getbyid@test.com",
    )

    found = professional_repository.get_by_id(professional.id)

    assert found is not None
    assert found.id == professional.id
    assert found.person_id == professional.person_id


def test_get_by_id_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    assert professional_repository.get_by_id(999999) is None


def test_create_application(
    professional_repository: ProfessionalRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11930000001")

    professional = professional_repository.create_application(
        person_id=person.id,
        area="Psicoterapia",
        professional_register=f"PENDING-{person.id}",
        register_type="PENDING_REVIEW",
        approach="TCC",
        background="Formação",
        video_platform="Meet",
        email="application@test.com",
    )

    found = professional_repository.get_by_person_id(person.id)

    assert found is not None
    assert found.id == professional.id
    assert found.area == "Psicoterapia"


def test_create_application_is_idempotent_per_person(
    professional_repository: ProfessionalRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11930000019")
    application_data = {
        "person_id": person.id,
        "area": "Psicoterapia",
        "professional_register": f"PENDING-{person.id}",
        "register_type": "PENDING_REVIEW",
        "approach": None,
        "background": None,
        "video_platform": None,
        "email": "idempotent@test.com",
    }

    first = professional_repository.create_application(**application_data)
    second = professional_repository.create_application(**application_data)

    assert second.id == first.id


def test_get_by_person_id(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000003"),
        professional_register="10003",
        email="getbyperson@test.com",
    )

    found = professional_repository.get_by_person_id(professional.person_id)

    assert found is not None
    assert found.id == professional.id
    assert found.person_id == professional.person_id


def test_get_by_person_id_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    assert professional_repository.get_by_person_id(999999) is None


def test_update(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000004"),
        professional_register="10004",
        email="before@test.com",
    )
    professional.email = "after@test.com"

    updated = professional_repository.update(professional)

    assert updated.email == "after@test.com"
    found = professional_repository.get_by_id(professional.id)
    assert found is not None
    assert found.email == "after@test.com"


def test_get_with_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000005"),
        professional_register="10005",
        email="withpatients@test.com",
    )
    patient_1 = make_patient(person=make_person(phone_number="11930000051"))
    patient_2 = make_patient(person=make_person(phone_number="11930000052"))
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
    )

    found = professional_repository.get_with_patients(professional.id)

    assert found is not None
    assert found.person.id == professional.person_id
    assert {patient.id for patient in found.patients} == {patient_1.id, patient_2.id}


def test_get_with_patients_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    assert professional_repository.get_with_patients(999999) is None


def test_get_patients_returns_empty_list(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000008"),
        professional_register="10008",
    )

    assert professional_repository.get_patients(professional.id) == []
    assert professional_repository.get_patients(999999) == []


def test_get_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000009"),
        professional_register="10009",
    )
    patients = [
        make_patient(person=make_person(phone_number="11930000091")),
        make_patient(person=make_person(phone_number="11930000092")),
    ]
    for patient in patients:
        make_professional_patient_link(
            professional_id=professional.id,
            patient_id=patient.id,
            created_at=datetime.utcnow(),
        )

    found_patients = professional_repository.get_patients(professional.id)

    assert {patient.id for patient in found_patients} == {patient.id for patient in patients}
