from __future__ import annotations

from collections.abc import Callable
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.domain.db.patient_model import PatientModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.db.professional_patient_model import ProfessionalPatientModel
from app.domain.enum.professional_status import ProfessionalStatus


class ProfessionalRepository:
    """Repository for managing Professional entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(self, professional: ProfessionalModel) -> ProfessionalModel:
        with self._session_factory() as session:
            session.add(professional)
            session.commit()
            session.refresh(professional)
            return professional

    def get_by_id(self, professional_id: int) -> ProfessionalModel | None:
        with self._session_factory() as session:
            stmt = select(ProfessionalModel).where(ProfessionalModel.id == professional_id)
            return session.scalar(stmt)

    def get_by_person_id(self, person_id: int) -> ProfessionalModel | None:
        with self._session_factory() as session:
            stmt = select(ProfessionalModel).where(ProfessionalModel.person_id == person_id)
            return session.scalar(stmt)

    def update(self, professional: ProfessionalModel) -> ProfessionalModel:
        with self._session_factory() as session:
            merged = session.merge(professional)
            session.commit()
            session.refresh(merged)
            return merged

    def get_with_patients(self, professional_id: int) -> ProfessionalModel | None:
        with self._session_factory() as session:
            stmt = (
                select(ProfessionalModel)
                .options(
                    joinedload(ProfessionalModel.patients).joinedload(PatientModel.person),
                    joinedload(ProfessionalModel.person),
                )
                .where(ProfessionalModel.id == professional_id)
            )
            return session.execute(stmt).unique().scalar_one_or_none()

    def count_patients(self, professional_id: int) -> int:
        with self._session_factory() as session:
            stmt = select(func.count(ProfessionalPatientModel.id)).where(
                ProfessionalPatientModel.professional_id == professional_id
            )
            count = session.scalar(stmt)
            return int(count or 0)

    def get_patients(self, professional_id: int) -> list[PatientModel]:
        with self._session_factory() as session:
            stmt = (
                select(ProfessionalModel)
                .options(joinedload(ProfessionalModel.patients))
                .where(ProfessionalModel.id == professional_id)
            )
            professional = session.execute(stmt).unique().scalar_one_or_none()
            if professional is None:
                return []
            return list(professional.patients)

    def get_active_professionals_with_less_than_n_patients(
        self,
        n: int,
    ) -> list[ProfessionalModel]:
        """Return active professionals whose current 30-day window has fewer than n new patients."""
        now = datetime.utcnow()

        with self._session_factory() as session:
            professionals = session.scalars(
                select(ProfessionalModel).where(
                    ProfessionalModel.status == ProfessionalStatus.ACTIVE,
                    ProfessionalModel.activated_at.is_not(None),
                )
            ).all()

            result: list[ProfessionalModel] = []

            for professional in professionals:
                assert professional.activated_at is not None

                elapsed = now - professional.activated_at
                completed_days = elapsed.days
                current_window_index = completed_days // 30

                window_start = professional.activated_at + timedelta(days=current_window_index * 30)
                window_end = window_start + timedelta(days=30)

                stmt = select(func.count(ProfessionalPatientModel.id)).where(
                    ProfessionalPatientModel.professional_id == professional.id,
                    ProfessionalPatientModel.created_at >= window_start,
                    ProfessionalPatientModel.created_at < window_end,
                )
                count = session.scalar(stmt)

                if int(count or 0) < n:
                    result.append(professional)

            return result

    def get_average_patients_per_professional_30_days(
        self,
    ) -> list[tuple[ProfessionalModel, float]]:
        """Return each active professional with the average number of new patients per 30-day window since activation."""
        now = datetime.utcnow()

        with self._session_factory() as session:
            professionals = session.scalars(
                select(ProfessionalModel).where(
                    ProfessionalModel.status == ProfessionalStatus.ACTIVE,
                    ProfessionalModel.activated_at.is_not(None),
                )
            ).all()

            if not professionals:
                return []

            professional_map = {professional.id: professional for professional in professionals}

            total_windows_by_professional: dict[int, int] = {}
            for professional in professionals:
                assert professional.activated_at is not None
                elapsed = now - professional.activated_at
                total_windows_by_professional[professional.id] = max(1, (elapsed.days // 30) + 1)

            links = session.scalars(
                select(ProfessionalPatientModel).where(
                    ProfessionalPatientModel.professional_id.in_(professional_map.keys())
                )
            ).all()

            counts_by_professional_and_window: dict[int, dict[int, int]] = defaultdict(
                lambda: defaultdict(int)
            )

            for link in links:
                professional = professional_map.get(link.professional_id)
                if professional is None or professional.activated_at is None:
                    continue

                if link.created_at < professional.activated_at:
                    continue

                elapsed_days = (link.created_at - professional.activated_at).days
                window_index = elapsed_days // 30

                if window_index < total_windows_by_professional[professional.id]:
                    counts_by_professional_and_window[professional.id][window_index] += 1

            result: list[tuple[ProfessionalModel, float]] = []

            for professional in professionals:
                total_windows = total_windows_by_professional[professional.id]
                window_counts = counts_by_professional_and_window[professional.id]
                total_patients = sum(window_counts.values())
                average = total_patients / total_windows
                result.append((professional, average))

            return result