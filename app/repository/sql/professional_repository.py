from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.db.professional_model import ProfessionalModel
from app.repository.sql.transaction import commit, session_scope


class ProfessionalRepository:
    """Repository for managing Professional entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(self, professional: ProfessionalModel) -> ProfessionalModel:
        with session_scope(self._session_factory) as session:
            session.add(professional)
            commit(session)
            session.refresh(professional)
            return professional

    def create_application(
        self,
        *,
        person_id: int,
        area: str,
        professional_register: str,
        register_type: str,
        approach: str | None,
        background: str | None,
        video_platform: str | None,
        email: str | None,
        gender: str | None = None,
        minority_group: str | None = None,
        created_at: datetime | None = None,
    ) -> ProfessionalModel:
        """Create a professional application unless one already exists."""
        with session_scope(self._session_factory) as session:
            existing = session.scalar(
                select(ProfessionalModel).where(
                    ProfessionalModel.person_id == person_id,
                )
            )
            if existing is not None:
                return existing

            professional = ProfessionalModel(
                person_id=person_id,
                area=area,
                professional_register=professional_register,
                register_type=register_type,
                approach=approach,
                background=background,
                video_platform=video_platform,
                email=email,
                gender=gender,
                minority_group=minority_group,
                created_at=created_at or datetime.utcnow(),
            )
            session.add(professional)
            commit(session)
            session.refresh(professional)
            return professional

    def get_by_id(self, professional_id: int) -> ProfessionalModel | None:
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalModel).options(joinedload(ProfessionalModel.person)).where(ProfessionalModel.id == professional_id)
            return session.execute(stmt).unique().scalar_one_or_none()

    def get_by_person_id(self, person_id: int) -> ProfessionalModel | None:
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalModel).options(joinedload(ProfessionalModel.person)).where(ProfessionalModel.person_id == person_id)
            return session.execute(stmt).unique().scalar_one_or_none()

    def update(self, professional: ProfessionalModel) -> ProfessionalModel:
        with session_scope(self._session_factory) as session:
            merged = session.merge(professional)
            commit(session)
            session.refresh(merged)
            return merged
