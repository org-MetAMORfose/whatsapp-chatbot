"""Resolve the exact allocation referenced by a matching completion event."""
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.domain.db.matching_model import MatchingCycleModel, MatchingSlotModel
from app.domain.db.patient_model import PatientModel
from app.domain.db.person_model import PersonModel
from app.domain.db.professional_model import ProfessionalModel
from app.domain.enum.channels import Channel
from app.domain.whatsapp.matching_patient_template import MatchingPatientTemplate


class MatchingNotificationRepository:
    def __init__(self, factory: Callable[[], Session]) -> None:
        self.factory = factory

    def resolve(self, patient_id: int, *, slot_id: int | None = None, cycle_id: int | None = None) -> MatchingPatientTemplate:
        patient_person = aliased(PersonModel)
        professional_person = aliased(PersonModel)
        statement = select(patient_person.phone_number, patient_person.channel, professional_person.name,
                           ProfessionalModel.area, professional_person.phone_number).select_from(MatchingSlotModel).join(
            PatientModel, PatientModel.id == MatchingSlotModel.patient_id,
        ).join(patient_person, patient_person.id == PatientModel.person_id).join(
            MatchingCycleModel, MatchingCycleModel.id == MatchingSlotModel.cycle_id,
        ).join(ProfessionalModel, ProfessionalModel.id == MatchingCycleModel.professional_id).join(
            professional_person, professional_person.id == ProfessionalModel.person_id,
        ).where(MatchingSlotModel.patient_id == patient_id)
        if slot_id is not None:
            statement = statement.where(MatchingSlotModel.id == slot_id)
        if cycle_id is not None:
            statement = statement.where(MatchingSlotModel.cycle_id == cycle_id)
        with self.factory() as session:
            row = session.execute(statement).one_or_none()
        if row is None:
            raise ValueError("Matching allocation or its patient/professional was not found")
        phone, channel, name, area, professional_phone = row
        if channel != Channel.WHATSAPP:
            raise ValueError("Matching patient does not have a WhatsApp contact")
        return MatchingPatientTemplate(phone, name, area, professional_phone)
