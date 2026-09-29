from __future__ import annotations

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
