from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.infra import create_session_factory
from app.domain.db.base import Base
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.db.patient_model import PatientModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.db.professional_patient_model import ProfessionalPatientModel
from app.domain.db.professional_status_history_model import (
    ProfessionalStatusHistoryModel,
)
from app.domain.enum.channels import Channel
from app.domain.enum.professional_status import ProfessionalStatus


@pytest.fixture
def engine(tmp_path) -> Iterator[Engine]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return create_session_factory(engine)


@pytest.fixture
def make_person(
    session_factory: sessionmaker[Session],
) -> Callable[..., PersonModel]:
    def _make_person(
        *,
        phone_number: str = "11999999999",
        name: str | None = None,
        cpf: str | None = None,
        channel: Channel | None = None,
        chat_state: str = "START",
        created_at: datetime | None = None,
    ) -> PersonModel:
        person = PersonModel(
            phone_number=phone_number,
            name=name,
            cpf=cpf,
            channel=channel,
            chat_state=chat_state,
            created_at=created_at or datetime.utcnow(),
        )
        with session_factory() as session:
            session.add(person)
            session.commit()
            session.refresh(person)
            return person

    return _make_person


@pytest.fixture
def make_professional_status_history(
    session_factory: sessionmaker[Session],
) -> Callable[..., ProfessionalStatusHistoryModel]:
    def _make_professional_status_history(
        *,
        professional_id: int,
        professional_status: ProfessionalStatus = ProfessionalStatus.REGISTER_PENDING,
        created_at: datetime | None = None,
    ) -> ProfessionalStatusHistoryModel:
        status_history = ProfessionalStatusHistoryModel(
            professional_id=professional_id,
            professional_status=professional_status,
            created_at=created_at or datetime.utcnow(),
        )
        with session_factory() as session:
            session.add(status_history)
            session.commit()
            session.refresh(status_history)
            return status_history

    return _make_professional_status_history


@pytest.fixture
def make_professional(
    session_factory: sessionmaker[Session],
    make_person: Callable[..., PersonModel],
) -> Callable[..., ProfessionalModel]:
    def _make_professional(
        *,
        person: PersonModel | None = None,
        area: str = "psychology",
        professional_register: str = "12345",
        register_type: str = "CRP",
        approach: str | None = None,
        background: str | None = None,
        video_platform: str | None = None,
        email: str | None = None,
        status: ProfessionalStatus = ProfessionalStatus.REGISTER_PENDING,
        status_created_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> ProfessionalModel:
        if person is None:
            person = make_person()

        with session_factory() as session:
            status_history = ProfessionalStatusHistoryModel(
                professional_id=0,
                professional_status=status,
                created_at=status_created_at or datetime.utcnow(),
            )

            professional = ProfessionalModel(
                person_id=person.id,
                area=area,
                professional_register=professional_register,
                register_type=register_type,
                approach=approach,
                background=background,
                video_platform=video_platform,
                email=email,
                status_id=0,
                created_at=created_at or datetime.utcnow(),
            )

            session.add(professional)
            session.flush()

            status_history.professional_id = professional.id
            session.add(status_history)
            session.flush()

            professional.status_id = status_history.id

            session.commit()
            session.refresh(professional)
            return professional

    return _make_professional


@pytest.fixture
def make_patient(
    session_factory: sessionmaker[Session],
    make_person: Callable[..., PersonModel],
) -> Callable[..., PatientModel]:
    def _make_patient(
        *,
        person: PersonModel | None = None,
        created_at: datetime | None = None,
    ) -> PatientModel:
        if person is None:
            person = make_person()

        patient = PatientModel(
            person_id=person.id,
            created_at=created_at or datetime.utcnow(),
        )
        with session_factory() as session:
            session.add(patient)
            session.commit()
            session.refresh(patient)
            return patient

    return _make_patient


@pytest.fixture
def make_message_history(
    session_factory: sessionmaker[Session],
) -> Callable[..., MessageHistoryModel]:
    def _make_message_history(
        *,
        person_id: int,
        content: str | None = None,
        image_url: str | None = None,
        document_url: str | None = None,
        is_from_user: bool = True,
        created_at: datetime | None = None,
    ) -> MessageHistoryModel:
        message = MessageHistoryModel(
            person_id=person_id,
            content=content,
            image_url=image_url,
            document_url=document_url,
            is_from_user=is_from_user,
            created_at=created_at or datetime.utcnow(),
        )
        with session_factory() as session:
            session.add(message)
            session.commit()
            session.refresh(message)
            return message

    return _make_message_history


@pytest.fixture
def make_professional_patient_link(
    session_factory: sessionmaker[Session],
) -> Callable[..., ProfessionalPatientModel]:
    def _make_professional_patient_link(
        *,
        professional_id: int,
        patient_id: int,
        created_at: datetime | None = None,
    ) -> ProfessionalPatientModel:
        link = ProfessionalPatientModel(
            professional_id=professional_id,
            patient_id=patient_id,
            created_at=created_at or datetime.utcnow(),
        )
        with session_factory() as session:
            session.add(link)
            session.commit()
            session.refresh(link)
            return link

    return _make_professional_patient_link