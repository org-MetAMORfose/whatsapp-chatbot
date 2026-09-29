from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.db.patient_model import PatientModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.db.professional_patient_model import ProfessionalPatientModel
from app.repository.sql.transaction import commit, session_scope


class PatientRepository:
    """Repository for managing Patient entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(self, patient: PatientModel) -> PatientModel:
        with session_scope(self._session_factory) as session:
            session.add(patient)
            commit(session)
            session.refresh(patient)
            return patient

    def get_by_id(self, patient_id: int) -> PatientModel | None:
        with session_scope(self._session_factory) as session:
            stmt = select(PatientModel).where(PatientModel.id == patient_id)
            return session.scalar(stmt)

    def get_by_person_id(self, person_id: int) -> PatientModel | None:
        """Return the most recent request for a person."""
        return self.get_latest_by_person_id(person_id)

    def exists_by_person_id(self, person_id: int) -> bool:
        """Return whether a person has at least one patient request."""
        with session_scope(self._session_factory) as session:
            stmt = (
                select(PatientModel.id)
                .where(PatientModel.person_id == person_id)
                .limit(1)
            )
            return session.scalar(stmt) is not None

    def get_latest_by_person_id(self, person_id: int) -> PatientModel | None:
        """Return the latest patient request for a person."""
        with session_scope(self._session_factory) as session:
            stmt = (
                select(PatientModel)
                .where(PatientModel.person_id == person_id)
                .order_by(PatientModel.created_at.desc(), PatientModel.id.desc())
                .limit(1)
            )
            return session.scalar(stmt)

    def get_professionals(self, patient_id: int) -> list[ProfessionalModel]:
        with session_scope(self._session_factory) as session:
            stmt = (
                select(PatientModel)
                .options(joinedload(PatientModel.professionals))
                .where(PatientModel.id == patient_id)
            )
            patient = session.scalar(stmt)
            if patient is None:
                return []
            return list(patient.professionals)

    def link_professional(
        self,
        *,
        patient_id: int,
        professional_id: int,
        created_at: datetime,
    ) -> ProfessionalPatientModel:
        with session_scope(self._session_factory) as session:
            link = ProfessionalPatientModel(
                patient_id=patient_id,
                professional_id=professional_id,
                created_at=created_at,
            )
            session.add(link)
            commit(session)
            session.refresh(link)
            return link

    def unlink_professional(
        self,
        *,
        patient_id: int,
        professional_id: int,
    ) -> bool:
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalPatientModel).where(
                ProfessionalPatientModel.patient_id == patient_id,
                ProfessionalPatientModel.professional_id == professional_id,
            )
            link = session.scalar(stmt)
            if link is None:
                return False

            session.delete(link)
            commit(session)
            return True

    def is_linked_to_professional(
        self,
        *,
        patient_id: int,
        professional_id: int,
    ) -> bool:
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalPatientModel.id).where(
                ProfessionalPatientModel.patient_id == patient_id,
                ProfessionalPatientModel.professional_id == professional_id,
            )
            return session.scalar(stmt) is not None
