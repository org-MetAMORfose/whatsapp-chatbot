from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.db.patient_model import PatientModel
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
