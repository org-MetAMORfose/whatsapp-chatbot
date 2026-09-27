"""Matching transactions using the same ORM models as the chatbot."""
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, lazyload

from app.domain.db.delivery_model import OutboxModel
from app.domain.db.matching_model import MatchingCycleModel as Cycle
from app.domain.db.matching_model import MatchingSlotModel as Slot
from app.domain.db.patient_model import PatientModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.chat_mode import ChatMode
from app.domain.matching import Candidate, MatchResult, Patient, PatientInput, PatientReference, PatientRegistration
from matching.domain import ALGORITHM_VERSION, rank, score_candidate


def used_slots() -> Select[tuple[int]]:
    return select(func.count(Slot.id)).where(Slot.cycle_id == Cycle.id).correlate(Cycle)


def candidates_for(area: str | None) -> Select[tuple[Cycle, ProfessionalModel, int]]:
    return select(Cycle, ProfessionalModel, used_slots().scalar_subquery().label("used")).join(
        ProfessionalModel, ProfessionalModel.id == Cycle.professional_id,
    ).where(ProfessionalModel.area == area, Cycle.cancelled_at.is_(None),
            Cycle.starts_at <= func.clock_timestamp(), Cycle.deadline_at > func.clock_timestamp())


def candidate_snapshot(cycle: Cycle, professional: ProfessionalModel, used: int) -> Candidate:
    return Candidate(id=cycle.id, professional_id=professional.id, area=professional.area, starts_at=cycle.starts_at,
        deadline_at=cycle.deadline_at, promised_patients=cycle.promised_patients, used=used,
        cancelled_at=cycle.cancelled_at, type=cycle.type, approach=professional.approach,
        gender=professional.gender, minority_group=professional.minority_group)


def register_patient(db: Session, data: PatientRegistration) -> int:
    db.execute(insert(PersonModel).values(phone_number=data.phone_number, channel=data.channel, name=data.name,
        birth_date=data.birth_date, chat_mode=ChatMode.AUTOMATIC, created_at=datetime.now(UTC)).on_conflict_do_nothing(
            index_elements=[PersonModel.phone_number, PersonModel.channel]))
    person_id = db.scalars(select(PersonModel.id).where(
        PersonModel.phone_number == data.phone_number, PersonModel.channel == data.channel).with_for_update()).one()
    patient = PatientModel(person_id=person_id, area=data.area, psychotherapy_approach=data.psychotherapy_approach,
        professional_profile=data.professional_profile, created_at=datetime.now(UTC))
    db.add(patient)
    db.flush()
    return patient.id


def allocate(db: Session, patient: Patient) -> MatchResult:
    existing = db.scalar(select(Slot).where(Slot.patient_id == patient.id))
    if existing:
        return MatchResult(patient.id, "matched", existing.id, existing.cycle_id)
    candidates = [candidate_snapshot(c, p, used) for c, p, used in db.execute(candidates_for(patient.area))]
    now = db.scalars(select(func.clock_timestamp())).one()
    for candidate, _ in rank(patient, candidates, now):
        db.execute(select(Cycle.id).where(Cycle.id == candidate.id).with_for_update()).all()
        db.execute(select(ProfessionalModel.id).where(ProfessionalModel.id == candidate.professional_id).with_for_update(read=True)).all()
        # ORM identity-map state must be refreshed after waiting for another writer.
        fresh = db.execute(candidates_for(patient.area).where(Cycle.id == candidate.id).execution_options(populate_existing=True)).one_or_none()
        if fresh is None:
            continue
        score = score_candidate(patient, candidate_snapshot(*fresh), db.scalars(select(func.clock_timestamp())).one())
        if score is None:
            continue
        slot = Slot(cycle_id=candidate.id, patient_id=patient.id, compatibility_score=score.compatibility,
            urgency_score=score.urgency, final_score=score.final, score_breakdown=asdict(score.breakdown),
            algorithm_version=ALGORITHM_VERSION, created_at=datetime.now(UTC))
        db.add(slot)
        db.flush()
        return MatchResult(patient.id, "matched", slot.id, slot.cycle_id)
    return MatchResult(patient.id, "no_capacity")


def execute(engine: Engine, data: PatientInput) -> MatchResult:
    with Session(engine) as db, db.begin():
        db.execute(select(func.set_config("lock_timeout", "5s", True)))
        db.execute(select(func.set_config("statement_timeout", "20s", True)))
        patient_id = data.patient_id if isinstance(data, PatientReference) else register_patient(db, data)
        patient = db.scalar(select(PatientModel).options(lazyload(PatientModel.person)).where(
            PatientModel.id == patient_id).with_for_update())
        result = allocate(db, Patient(patient.id, patient.area, patient.psychotherapy_approach, patient.professional_profile)) if patient else (
            MatchResult(patient_id, "patient_not_found"))
        db.add(OutboxModel(id=f"matching:result:{uuid4()}", kind="matching.completed", payload=result.as_payload()))
        return result


def match_pending(engine: Engine, limit: int = 100) -> list[MatchResult]:
    available = select(Cycle.id).join(ProfessionalModel, ProfessionalModel.id == Cycle.professional_id).where(
        ProfessionalModel.area == PatientModel.area, Cycle.cancelled_at.is_(None),
        Cycle.starts_at <= func.clock_timestamp(), Cycle.deadline_at > func.clock_timestamp(),
        used_slots().scalar_subquery() < Cycle.promised_patients).correlate(PatientModel).exists()
    assigned = select(Slot.id).where(Slot.patient_id == PatientModel.id).exists()
    with Session(engine) as db:
        patients = db.scalars(select(PatientModel.id).where(~assigned, available).order_by(
            PatientModel.created_at, PatientModel.id).limit(min(100, max(0, limit)))).all()
    return [execute(engine, PatientReference(patient_id)) for patient_id in patients]
