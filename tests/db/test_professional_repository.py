from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.professional_model import ProfessionalModel
from app.domain.db.professional_status_history_model import (
    ProfessionalStatusHistoryModel,
)
from app.domain.enum.professional_status import ProfessionalStatus
from app.repository.professional_repository import ProfessionalRepository


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
    assert found.current_status is not None
    assert found.current_status.professional_status == ProfessionalStatus.REGISTER_PENDING


def test_get_by_id_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    found = professional_repository.get_by_id(999999)

    assert found is None


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
    assert found.current_status is not None
    assert found.current_status.professional_status == ProfessionalStatus.REGISTER_PENDING


def test_get_by_person_id_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    found = professional_repository.get_by_person_id(999999)

    assert found is None


def test_update(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000004"),
        professional_register="10004",
        email="before@test.com",
        status=ProfessionalStatus.REGISTER_PENDING,
    )

    professional.email = "after@test.com"

    updated = professional_repository.update(professional)

    assert updated.email == "after@test.com"

    found = professional_repository.get_by_id(professional.id)
    assert found is not None
    assert found.email == "after@test.com"
    assert found.current_status is not None
    assert found.current_status.professional_status == ProfessionalStatus.REGISTER_PENDING


def test_update_status(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000040"),
        professional_register="10040",
        email="status@test.com",
        status=ProfessionalStatus.REGISTER_PENDING,
    )

    updated = professional_repository.update_status(
        professional.id,
        ProfessionalStatus.ACTIVE,
        created_at=now,
    )

    assert updated is not None
    assert updated.status_id != professional.status_id
    assert updated.current_status is not None
    assert updated.current_status.professional_status == ProfessionalStatus.ACTIVE
    assert updated.current_status.created_at == now
    assert len(updated.status_history) == 2

    found = professional_repository.get_by_id(professional.id)
    assert found is not None
    assert found.current_status is not None
    assert found.current_status.professional_status == ProfessionalStatus.ACTIVE
    assert found.current_status.created_at == now
    assert len(found.status_history) == 2


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
        created_at=datetime.utcnow(),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=datetime.utcnow(),
    )

    found = professional_repository.get_with_patients(professional.id)

    assert found is not None
    assert found.id == professional.id
    assert found.person is not None
    assert found.person.id == professional.person_id
    assert len(found.patients) == 2

    patient_ids = {patient.id for patient in found.patients}
    assert patient_ids == {patient_1.id, patient_2.id}


def test_get_with_patients_returns_none_when_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    found = professional_repository.get_with_patients(999999)

    assert found is None


def test_get_patients_returns_empty_list_when_professional_has_no_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000008"),
        professional_register="10008",
        email="emptypatients@test.com",
    )

    patients = professional_repository.get_patients(professional.id)

    assert patients == []


def test_get_patients_returns_empty_list_when_professional_not_found(
    professional_repository: ProfessionalRepository,
) -> None:
    patients = professional_repository.get_patients(999999)

    assert patients == []


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
        email="patients@test.com",
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

    assert len(found_patients) == 2
    patient_ids = {patient.id for patient in found_patients}
    expected_ids = {patient.id for patient in patients}
    assert patient_ids == expected_ids


def test_get_active_professionals_with_less_than_n_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional_1 = make_professional(
        person=make_person(phone_number="11930000010"),
        professional_register="10010",
        email="active1@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=45),
    )
    professional_2 = make_professional(
        person=make_person(phone_number="11930000011"),
        professional_register="10011",
        email="active2@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=45),
    )
    inactive_professional = make_professional(
        person=make_person(phone_number="11930000012"),
        professional_register="10012",
        email="inactive@test.com",
        status=ProfessionalStatus.INACTIVE,
        status_created_at=now - timedelta(days=45),
    )

    patients = [
        make_patient(person=make_person(phone_number="11930000101")),
        make_patient(person=make_person(phone_number="11930000102")),
        make_patient(person=make_person(phone_number="11930000103")),
        make_patient(person=make_person(phone_number="11930000104")),
        make_patient(person=make_person(phone_number="11930000105")),
        make_patient(person=make_person(phone_number="11930000106")),
    ]

    p1 = professional_repository.get_by_id(professional_1.id)
    p2 = professional_repository.get_by_id(professional_2.id)

    assert p1 is not None
    assert p2 is not None

    activated_at_1 = p1.current_status.created_at
    activated_at_2 = p2.current_status.created_at

    current_window_start_1 = activated_at_1 + timedelta(days=30)
    current_window_start_2 = activated_at_2 + timedelta(days=30)

    # profissional 1 -> 2 pacientes na janela atual
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[0].id,
        created_at=current_window_start_1 + timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[1].id,
        created_at=current_window_start_1 + timedelta(days=2),
    )

    # profissional 1 -> 1 paciente fora da janela atual
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[5].id,
        created_at=current_window_start_1 + timedelta(days=31),
    )

    # profissional 2 -> 3 pacientes na janela atual
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[2].id,
        created_at=current_window_start_2 + timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[3].id,
        created_at=current_window_start_2 + timedelta(days=2),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[4].id,
        created_at=current_window_start_2 + timedelta(days=3),
    )

    result = professional_repository.get_active_professionals_with_less_than_n_patients(3)

    result_ids = {professional.id for professional in result}

    assert professional_1.id in result_ids
    assert professional_2.id not in result_ids
    assert inactive_professional.id not in result_ids


def test_get_active_professionals_with_less_than_n_patients_ignores_previous_windows(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000013"),
        professional_register="10013",
        email="previouswindow@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=45),
    )

    patient_1 = make_patient(person=make_person(phone_number="11930000111"))
    patient_2 = make_patient(person=make_person(phone_number="11930000112"))
    patient_3 = make_patient(person=make_person(phone_number="11930000113"))

    found_professional = professional_repository.get_by_id(professional.id)
    assert found_professional is not None
    first_window_start = found_professional.current_status.created_at
    second_window_start = first_window_start + timedelta(days=30)

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
        created_at=first_window_start + timedelta(days=5),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=first_window_start + timedelta(days=10),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_3.id,
        created_at=second_window_start + timedelta(days=1),
    )

    result = professional_repository.get_active_professionals_with_less_than_n_patients(2)

    result_ids = {prof.id for prof in result}

    assert professional.id in result_ids


def test_get_average_patients_per_professional_30_days(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional_1 = make_professional(
        person=make_person(phone_number="11930000015"),
        professional_register="10015",
        email="avg1@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=75),
    )
    professional_2 = make_professional(
        person=make_person(phone_number="11930000016"),
        professional_register="10016",
        email="avg2@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=75),
    )

    found_professional_1 = professional_repository.get_by_id(professional_1.id)
    found_professional_2 = professional_repository.get_by_id(professional_2.id)
    assert found_professional_1 is not None
    assert found_professional_2 is not None

    activated_at_1 = found_professional_1.current_status.created_at
    activated_at_2 = found_professional_2.current_status.created_at

    patients = [
        make_patient(person=make_person(phone_number="11930000131")),
        make_patient(person=make_person(phone_number="11930000132")),
        make_patient(person=make_person(phone_number="11930000133")),
        make_patient(person=make_person(phone_number="11930000134")),
        make_patient(person=make_person(phone_number="11930000135")),
    ]

    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[0].id,
        created_at=activated_at_1 + timedelta(days=5),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[1].id,
        created_at=activated_at_1 + timedelta(days=35),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[2].id,
        created_at=activated_at_1 + timedelta(days=65),
    )

    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[3].id,
        created_at=activated_at_2 + timedelta(days=10),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[4].id,
        created_at=activated_at_2 + timedelta(days=20),
    )

    averages = professional_repository.get_average_patients_per_professional_30_days()
    average_map = {professional.id: average for professional, average in averages}

    assert average_map[professional_1.id] == pytest.approx(1.0)
    assert average_map[professional_2.id] == pytest.approx(2 / 3)


def test_get_average_patients_per_professional_30_days_ignores_links_before_activation(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000017"),
        professional_register="10017",
        email="beforeactivation@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=45),
    )

    found_professional = professional_repository.get_by_id(professional.id)
    assert found_professional is not None
    activated_at = found_professional.current_status.created_at

    patient_1 = make_patient(person=make_person(phone_number="11930000141"))
    patient_2 = make_patient(person=make_person(phone_number="11930000142"))

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
        created_at=activated_at - timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=activated_at + timedelta(days=10),
    )

    averages = professional_repository.get_average_patients_per_professional_30_days()
    average_map = {prof.id: average for prof, average in averages}

    assert average_map[professional.id] == 0.5


def test_get_average_patients_per_professional_30_days_returns_empty_when_no_active_professionals(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    now = datetime.utcnow()

    make_professional(
        person=make_person(phone_number="11930000018"),
        professional_register="10018",
        email="inactive@test.com",
        status=ProfessionalStatus.INACTIVE,
        status_created_at=now - timedelta(days=20),
    )

    averages = professional_repository.get_average_patients_per_professional_30_days()

    assert averages == []


def test_get_active_professionals_with_less_than_n_patients_uses_current_active_status_date(
    professional_repository: ProfessionalRepository,
    session_factory: sessionmaker[Session],
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000020"),
        professional_register="10020",
        email="currentactivewindow@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=90),
    )

    with session_factory() as session:
        new_active_status = ProfessionalStatusHistoryModel(
            professional_id=professional.id,
            professional_status=ProfessionalStatus.ACTIVE,
            created_at=now - timedelta(days=20),
        )
        session.add(new_active_status)
        session.flush()

        db_professional = session.get(ProfessionalModel, professional.id)
        assert db_professional is not None
        db_professional.status_id = new_active_status.id

        session.commit()

    patient_1 = make_patient(person=make_person(phone_number="11930000151"))
    patient_2 = make_patient(person=make_person(phone_number="11930000152"))
    patient_3 = make_patient(person=make_person(phone_number="11930000153"))

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
        created_at=now - timedelta(days=80),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=now - timedelta(days=75),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_3.id,
        created_at=now - timedelta(days=10),
    )

    result = professional_repository.get_active_professionals_with_less_than_n_patients(2)
    result_ids = {prof.id for prof in result}

    assert professional.id in result_ids


def test_get_average_patients_per_professional_30_days_uses_current_active_status_date(
    professional_repository: ProfessionalRepository,
    session_factory: sessionmaker[Session],
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000021"),
        professional_register="10021",
        email="currentactiveavg@test.com",
        status=ProfessionalStatus.ACTIVE,
        status_created_at=now - timedelta(days=90),
    )

    with session_factory() as session:
        new_active_status = ProfessionalStatusHistoryModel(
            professional_id=professional.id,
            professional_status=ProfessionalStatus.ACTIVE,
            created_at=now - timedelta(days=20),
        )
        session.add(new_active_status)
        session.flush()

        db_professional = session.get(ProfessionalModel, professional.id)
        assert db_professional is not None
        db_professional.status_id = new_active_status.id

        session.commit()

    patient_1 = make_patient(person=make_person(phone_number="11930000161"))
    patient_2 = make_patient(person=make_person(phone_number="11930000162"))

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
        created_at=now - timedelta(days=80),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=now - timedelta(days=10),
    )

    averages = professional_repository.get_average_patients_per_professional_30_days()
    average_map = {prof.id: average for prof, average in averages}

    assert average_map[professional.id] == pytest.approx(1.0)