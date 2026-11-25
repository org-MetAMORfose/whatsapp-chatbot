from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.immediate_eligibility import is_eligible_for_immediate, works_in_area
from app.domain.matching.profile import professional_profile
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
        matching_profile: dict[str, Any] | None = None,
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
                matching_profile=matching_profile or professional_profile(
                    areas=[area], approaches=[approach] if approach else [],
                    gender=gender, minority_group=minority_group,
                ),
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

    def get_by_phone_numbers(self, phone_numbers: Sequence[str], channel: Channel) -> ProfessionalModel | None:
        """The professional whose person has one of these numbers (the same phone written in different forms)."""
        if not phone_numbers:
            return None
        with session_scope(self._session_factory) as session:
            stmt = (
                select(ProfessionalModel)
                .join(ProfessionalModel.person)
                .options(joinedload(ProfessionalModel.person))
                .where(PersonModel.phone_number.in_(list(phone_numbers)), PersonModel.channel == channel)
                .order_by(ProfessionalModel.id)
            )
            return session.execute(stmt).unique().scalars().first()

    def update(self, professional: ProfessionalModel) -> ProfessionalModel:
        with session_scope(self._session_factory) as session:
            merged = session.merge(professional)
            commit(session)
            session.refresh(merged)
            return merged

    def set_available_for_immediate(self, person_id: int, available: bool, *, now: datetime) -> ProfessionalModel | None:
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalModel).options(joinedload(ProfessionalModel.person)).where(ProfessionalModel.person_id == person_id)
            professional = session.execute(stmt).unique().scalar_one_or_none()
            if professional is None:
                return None
            professional.available_for_immediate = available
            professional.immediate_availability_updated_at = now
            commit(session)
            session.refresh(professional)
            return professional

    def set_immediate_approval(self, professional_id: int, approved: bool, *, now: datetime) -> ProfessionalModel | None:
        """Release (or withdraw) a professional for immediate care; withdrawing also switches availability off."""
        with session_scope(self._session_factory) as session:
            stmt = select(ProfessionalModel).options(joinedload(ProfessionalModel.person)).where(ProfessionalModel.id == professional_id)
            professional = session.execute(stmt).unique().scalar_one_or_none()
            if professional is None:
                return None
            if approved:
                professional.immediate_approved_at = professional.immediate_approved_at or now
            else:
                professional.immediate_approved_at = None
                if professional.available_for_immediate:
                    professional.available_for_immediate = False
                    professional.immediate_availability_updated_at = now
            commit(session)
            session.refresh(professional)
            return professional

    def list_available_for_immediate(self, area: str | None = None) -> list[ProfessionalModel]:
        """Released professionals who opted in to immediate care (of one area, when given), with their person loaded."""
        with session_scope(self._session_factory) as session:
            stmt = (
                select(ProfessionalModel)
                .options(joinedload(ProfessionalModel.person))
                .where(ProfessionalModel.available_for_immediate.is_(True))
                .order_by(ProfessionalModel.id)
            )
            return [
                professional
                for professional in session.execute(stmt).unique().scalars().all()
                if is_eligible_for_immediate(professional) and works_in_area(professional, area)
            ]
