from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.professional_status import ProfessionalStatus
from app.repository.professional_repository import ProfessionalRepository


@pytest.fixture
def professional_repository(
    session_factory: sessionmaker[Session],
) -> ProfessionalRepository:
    return ProfessionalRepository(session_factory)


def test_create(
    professional_repository: ProfessionalRepository,
    make_person,
) -> None:
    person = make_person(phone_number="11930000001")

    professional = ProfessionalModel(
        person_id=person.id,
        area="psychology",
        professional_register="10001",
        register_type="CRP",
        approach="CBT",
        background="Clinical psychologist",
        video_platform="Google Meet",
        email="create@test.com",
        created_at=datetime.utcnow(),
    )

    created = professional_repository.create(professional)

    assert created.id is not None
    assert created.person_id == person.id
    assert created.area == "psychology"
    assert created.professional_register == "10001"
    assert created.register_type == "CRP"
    assert created.status == ProfessionalStatus.REGISTER_PENDING


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
    now = datetime.utcnow()

    professional = make_professional(
        person=make_person(phone_number="11930000004"),
        professional_register="10004",
        email="before@test.com",
        status=ProfessionalStatus.REGISTER_PENDING,
    )

    professional.email = "after@test.com"
    professional.status = ProfessionalStatus.ACTIVE
    professional.approved_at = now
    professional.activated_at = now

    updated = professional_repository.update(professional)

    assert updated.email == "after@test.com"
    assert updated.status == ProfessionalStatus.ACTIVE
    assert updated.activated_at == now

    found = professional_repository.get_by_id(professional.id)
    assert found is not None
    assert found.email == "after@test.com"
    assert found.status == ProfessionalStatus.ACTIVE
    assert found.activated_at == now


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


def test_count_patients_returns_zero_when_professional_has_no_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_person,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000006"),
        professional_register="10006",
        email="countzero@test.com",
    )

    count = professional_repository.count_patients(professional.id)

    assert count == 0


def test_count_patients(
    professional_repository: ProfessionalRepository,
    make_professional,
    make_patient,
    make_person,
    make_professional_patient_link,
) -> None:
    professional = make_professional(
        person=make_person(phone_number="11930000007"),
        professional_register="10007",
        email="count@test.com",
    )

    patients = [
        make_patient(person=make_person(phone_number="11930000071")),
        make_patient(person=make_person(phone_number="11930000072")),
        make_patient(person=make_person(phone_number="11930000073")),
    ]

    for patient in patients:
        make_professional_patient_link(
            professional_id=professional.id,
            patient_id=patient.id,
            created_at=datetime.utcnow(),
        )

    count = professional_repository.count_patients(professional.id)

    assert count == 3


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
        activated_at=now - timedelta(days=45),
    )
    professional_2 = make_professional(
        person=make_person(phone_number="11930000011"),
        professional_register="10011",
        email="active2@test.com",
        status=ProfessionalStatus.ACTIVE,
        activated_at=now - timedelta(days=45),
    )
    inactive_professional = make_professional(
        person=make_person(phone_number="11930000012"),
        professional_register="10012",
        email="inactive@test.com",
        status=ProfessionalStatus.INACTIVE,
        activated_at=now - timedelta(days=45),
    )

    patients = [
        make_patient(person=make_person(phone_number="11930000101")),
        make_patient(person=make_person(phone_number="11930000102")),
        make_patient(person=make_person(phone_number="11930000103")),
        make_patient(person=make_person(phone_number="11930000104")),
        make_patient(person=make_person(phone_number="11930000105")),
    ]

    current_window_start = professional_1.activated_at + timedelta(days=30)

    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[0].id,
        created_at=current_window_start + timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[1].id,
        created_at=current_window_start + timedelta(days=2),
    )

    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[2].id,
        created_at=current_window_start + timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[3].id,
        created_at=current_window_start + timedelta(days=2),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[4].id,
        created_at=current_window_start + timedelta(days=3),
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
        activated_at=now - timedelta(days=45),
    )

    patient_1 = make_patient(person=make_person(phone_number="11930000111"))
    patient_2 = make_patient(person=make_person(phone_number="11930000112"))
    patient_3 = make_patient(person=make_person(phone_number="11930000113"))

    first_window_start = professional.activated_at
    second_window_start = professional.activated_at + timedelta(days=30)

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
        activated_at=now - timedelta(days=75),
    )
    professional_2 = make_professional(
        person=make_person(phone_number="11930000016"),
        professional_register="10016",
        email="avg2@test.com",
        status=ProfessionalStatus.ACTIVE,
        activated_at=now - timedelta(days=75),
    )

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
        created_at=professional_1.activated_at + timedelta(days=5),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[1].id,
        created_at=professional_1.activated_at + timedelta(days=35),
    )
    make_professional_patient_link(
        professional_id=professional_1.id,
        patient_id=patients[2].id,
        created_at=professional_1.activated_at + timedelta(days=65),
    )

    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[3].id,
        created_at=professional_2.activated_at + timedelta(days=10),
    )
    make_professional_patient_link(
        professional_id=professional_2.id,
        patient_id=patients[4].id,
        created_at=professional_2.activated_at + timedelta(days=20),
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
        activated_at=now - timedelta(days=45),
    )

    patient_1 = make_patient(person=make_person(phone_number="11930000141"))
    patient_2 = make_patient(person=make_person(phone_number="11930000142"))

    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_1.id,
        created_at=professional.activated_at - timedelta(days=1),
    )
    make_professional_patient_link(
        professional_id=professional.id,
        patient_id=patient_2.id,
        created_at=professional.activated_at + timedelta(days=10),
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
        activated_at=now - timedelta(days=20),
    )
    make_professional(
        person=make_person(phone_number="11930000019"),
        professional_register="10019",
        email="nostart@test.com",
        status=ProfessionalStatus.ACTIVE,
        activated_at=None,
    )

    averages = professional_repository.get_average_patients_per_professional_30_days()

    assert averages == []
