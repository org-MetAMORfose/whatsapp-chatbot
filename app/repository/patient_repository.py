from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.db.patient_model import PatientModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.db.professional_patient_model import ProfessionalPatientModel


class PatientRepository:
    """Repository for managing Patient entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(self, patient: PatientModel) -> PatientModel:
        with self._session_factory() as session:
            session.add(patient)
            session.commit()
            session.refresh(patient)
            return patient

    def get_by_id(self, patient_id: int) -> PatientModel | None:
        with self._session_factory() as session:
            stmt = select(PatientModel).where(PatientModel.id == patient_id)
            return session.scalar(stmt)

    def get_by_person_id(self, person_id: int) -> PatientModel | None:
        with self._session_factory() as session:
            stmt = select(PatientModel).where(PatientModel.person_id == person_id)
            return session.scalar(stmt)

    def get_professionals(self, patient_id: int) -> list[ProfessionalModel]:
        with self._session_factory() as session:
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
        with self._session_factory() as session:
            link = ProfessionalPatientModel(
                patient_id=patient_id,
                professional_id=professional_id,
                created_at=created_at,
            )
            session.add(link)
            session.commit()
            session.refresh(link)
            return link

    def unlink_professional(
        self,
        *,
        patient_id: int,
        professional_id: int,
    ) -> bool:
        with self._session_factory() as session:
            stmt = select(ProfessionalPatientModel).where(
                ProfessionalPatientModel.patient_id == patient_id,
                ProfessionalPatientModel.professional_id == professional_id,
            )
            link = session.scalar(stmt)
            if link is None:
                return False

            session.delete(link)
            session.commit()
            return True

    def is_linked_to_professional(
        self,
        *,
        patient_id: int,
        professional_id: int,
    ) -> bool:
        with self._session_factory() as session:
            stmt = select(ProfessionalPatientModel.id).where(
                ProfessionalPatientModel.patient_id == patient_id,
                ProfessionalPatientModel.professional_id == professional_id,
            )
            return session.scalar(stmt) is not None