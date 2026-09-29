from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.domain.db  # noqa: F401 - register all tables in Base.metadata
from app.domain.db.base import Base
from app.domain.db.delivery_model import OutboxModel
from app.domain.db.patient_model import PatientModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.services.registration_service import (
    PatientRegistrationData,
    ProfessionalRegistrationData,
    RegistrationService,
)


def _service(tmp_path) -> tuple[RegistrationService, sessionmaker[Session]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'registration.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return (
        RegistrationService(
            factory,
            PersonRepository(factory),
            PatientRepository(factory),
            ProfessionalRepository(factory),
            OutboxRepository(factory),
        ),
        factory,
    )


def test_register_patient_batch_persists_matching_requests_atomically(tmp_path) -> None:
    service, factory = _service(tmp_path)

    result = service.register_patients(
        [
            PatientRegistrationData(
                name="Ana",
                phone="5511999991111",
                area="Psicoterapia",
                birth_date=date(1990, 1, 31),
            ),
            PatientRegistrationData(
                name="Bia",
                phone="5511999992222",
                area="Nutrição",
            ),
        ]
    )

    assert len(result) == 2
    with factory() as session:
        assert session.query(PersonModel).count() == 2
        assert session.query(PatientModel).count() == 2
        requests = session.scalars(
            select(OutboxModel).order_by(OutboxModel.id)
        ).all()
        assert len(requests) == 2
        assert {request.kind for request in requests} == {"matching.requested"}
        assert {request.payload["patient_id"] for request in requests} == {
            patient.id for patient in result
        }


def test_register_professional_persists_optional_profile(tmp_path) -> None:
    service, factory = _service(tmp_path)

    result = service.register_professional(
        ProfessionalRegistrationData(
            name="Carla",
            phone="5511988887777",
            email="carla@example.com",
            area="Psicoterapia",
            approach="TCC",
            gender="Feminino",
        )
    )

    with factory() as session:
        professional = session.get(ProfessionalModel, result.id)
        person = session.get(PersonModel, result.person_id)
        assert professional is not None
        assert person is not None
        assert person.name == "Carla"
        assert professional.email == "carla@example.com"
        assert professional.approach == "TCC"
        assert professional.register_type == "PENDING_REVIEW"
        assert professional.professional_register == f"PENDING-{person.id}"
