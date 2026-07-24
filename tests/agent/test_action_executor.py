from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.action_executor import ActionExecutor, ActionResult
from app.domain.db.patient_model import PatientModel
from app.domain.enum.channels import Channel
from app.domain.enum.chat_state import ChatState
from app.domain.message import Message
from app.domain.patient_stage import PatientStageContext
from app.domain.professional_stage import ProfessionalStageContext
from app.services.google_sheets_service import GoogleSheetsServiceError


def make_message(content: str | None = None) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime(2026, 6, 22),
        user_id="5511999999999",
        chat_id="chat-1",
        content=content,
    )


def make_executor() -> tuple[
    ActionExecutor, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock
]:
    stage_repository = MagicMock()
    professional_repository = MagicMock()
    person_repository = MagicMock()
    patient_repository = MagicMock()
    patient_stage_repository = MagicMock()
    google_sheets_service = MagicMock()
    executor = ActionExecutor(
        stage_repository,
        professional_repository,
        person_repository,
        patient_repository,
        patient_stage_repository,
        google_sheets_service,
    )
    return (
        executor,
        stage_repository,
        professional_repository,
        person_repository,
        patient_stage_repository,
        google_sheets_service,
    )


@pytest.mark.asyncio
async def test_set_chat_state_delegates_priority_check_to_repository() -> None:
    executor, _, _, person_repository, _, _ = make_executor()
    message = make_message()

    await executor.postgres_set_chat_state(
        message,
        chat_state=ChatState.PAYMENT_RENEWAL,
    )

    person_repository.update_chat_state_by_contact.assert_called_once_with(
        phone_number=message.user_id,
        channel=message.channel,
        chat_state=ChatState.PAYMENT_RENEWAL,
    )


@pytest.mark.asyncio
async def test_professional_support_only_marks_other_subjects() -> None:
    executor, _, _, person_repository, _, _ = make_executor()

    await executor.postgres_set_professional_support_state(
        make_message("Renovaçã por Pix"),
    )
    person_repository.update_chat_state_by_contact.assert_not_called()

    await executor.postgres_set_professional_support_state(
        make_message("Outros assuntos"),
    )
    person_repository.update_chat_state_by_contact.assert_called_once()


@pytest.mark.asyncio
async def test_new_patient_only_marks_session_request() -> None:
    executor, _, _, person_repository, _, _ = make_executor()

    await executor.postgres_set_new_patient_state(
        make_message("Tenho dúvida"),
    )
    person_repository.update_chat_state_by_contact.assert_not_called()

    await executor.postgres_set_new_patient_state(
        make_message("Quero sessão"),
    )
    person_repository.update_chat_state_by_contact.assert_called_once()


@pytest.mark.asyncio
async def test_route_patient_registration_starts_first_registration() -> None:
    executor, _, _, person_repository, patient_stage_repository, _ = make_executor()
    message = make_message("Atendimento normal")
    person_repository.get_by_phone_number_and_channel.return_value = MagicMock(id=42)
    executor.patient_repository.exists_by_person_id.return_value = False
    patient_stage_repository.create_context = AsyncMock()

    result = await executor.postgres_route_patient_registration(message)

    assert result == ActionResult(next_node="paciente_nome")
    patient_stage_repository.create_context.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_route_patient_registration_loads_latest_request_for_returning_patient() -> None:
    executor, _, _, person_repository, patient_stage_repository, _ = make_executor()
    message = make_message("Atendimento normal")
    person_repository.get_by_phone_number_and_channel.return_value = MagicMock(
        id=42,
        name="Maria",
    )
    executor.patient_repository.exists_by_person_id.return_value = True
    executor.patient_repository.get_latest_by_person_id.return_value = MagicMock(
        area="Psicoterapia",
        psychotherapy_approach="TCC",
        professional_profile="Mulher",
        price_range="Até R$300",
    )
    context = PatientStageContext(
        user_id=message.user_id,
        chat_id=message.chat_id,
        channel=message.channel,
        name="Maria",
        area="Psicoterapia",
        psychotherapy_approach="TCC",
        professional_profile="Mulher",
        price_range="Até R$300",
        is_returning=True,
    )
    patient_stage_repository.create_context = AsyncMock()
    patient_stage_repository.update_context = AsyncMock(return_value=context)

    result = await executor.postgres_route_patient_registration(message)

    assert result.next_node == "paciente_retorno_resumo"
    assert "- Nome: Maria" in result.output
    assert "- Telefone: 5511999999999" in result.output
    patient_stage_repository.update_context.assert_awaited_once()


@pytest.mark.asyncio
async def test_returning_patient_only_sees_approach_for_psychotherapy() -> None:
    executor, _, _, _, patient_stage_repository, _ = make_executor()
    message = make_message("Atualizar")
    patient_stage_repository.get_context = AsyncMock(
        return_value=PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            area="Psiquiatria",
            psychotherapy_approach=None,
            professional_profile="LGBTQIAPN+",
            is_returning=True,
        )
    )

    result = await executor.postgres_route_patient_preference_update(message)

    assert result.next_node == "paciente_retorno_campos_geral"

    patient_stage_repository.get_context = AsyncMock(
        return_value=PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            area="Psicoterapia",
            psychotherapy_approach="TCC",
            is_returning=True,
        )
    )
    result = await executor.postgres_route_patient_preference_update(message)

    assert result.next_node == "paciente_retorno_campos_psicoterapia"


@pytest.mark.asyncio
async def test_changing_to_non_psychotherapy_clears_only_approach() -> None:
    executor, _, _, _, patient_stage_repository, _ = make_executor()
    patient_stage_repository.update_context = AsyncMock()
    message = make_message("Psiquiatria")

    await executor.redis_update_patient(
        message,
        field="area",
    )

    patient_stage_repository.update_context.assert_awaited_once_with(
        message,
        {"area": "Psiquiatria", "psychotherapy_approach": None},
    )


@pytest.mark.asyncio
async def test_register_new_patient_request_persists_preferences_and_sets_state() -> None:
    executor, _, _, person_repository, patient_stage_repository, _ = make_executor()
    message = make_message("Até R$300")
    person = MagicMock(id=42, name=None)
    person_repository.get_by_phone_number_and_channel.return_value = person
    patient_stage_repository.get_context = AsyncMock(
        return_value=PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            area="Psicoterapia",
            psychotherapy_approach="TCC",
            professional_profile="Mulher",
            price_range="Até R$300",
        )
    )

    await executor.postgres_register_new_patient_request(message)

    person_repository.update.assert_called_once_with(person)
    created_patient = executor.patient_repository.create.call_args.args[0]
    assert isinstance(created_patient, PatientModel)
    assert created_patient.person_id == 42
    assert created_patient.area == "Psicoterapia"
    assert created_patient.psychotherapy_approach == "TCC"
    person_repository.update_chat_state_by_contact.assert_called_once_with(
        phone_number=message.user_id,
        channel=message.channel,
        chat_state=ChatState.NEW_PATIENT,
    )


@pytest.mark.asyncio
async def test_register_professional_application_from_stage() -> None:
    executor, stage_repository, professional_repository, person_repository, _, _ = (
        make_executor()
    )
    message = make_message()
    stage_repository.get_context = AsyncMock(
        return_value=ProfessionalStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            email="maria@example.com",
            area="Psicoterapia",
            qualification="Formação",
            video_tool="Meet",
            approach="TCC",
        )
    )
    person = MagicMock(id=42, name=None)
    person_repository.get_by_phone_number_and_channel.return_value = person

    await executor.postgres_register_professional_application(message)

    assert person.name == "Maria"
    person_repository.update.assert_called_once_with(person)
    professional_repository.create_application.assert_called_once_with(
        person_id=42,
        area="Psicoterapia",
        professional_register="PENDING-42",
        register_type="PENDING_REVIEW",
        approach="TCC",
        background="Formação",
        video_platform="Meet",
        email="maria@example.com",
        created_at=message.created_at,
    )


@pytest.mark.asyncio
async def test_redis_update_patient_stores_field() -> None:
    executor, _, _, _, patient_stage_repository, _ = make_executor()
    patient_stage_repository.update_context = AsyncMock()
    message = make_message("Maria")

    await executor.redis_update_patient(message, field="name")

    patient_stage_repository.update_context.assert_called_once_with(
        message,
        {"name": "Maria"},
    )


@pytest.mark.asyncio
async def test_sheets_register_patient_writes_stage_data() -> None:
    executor, _, _, _, patient_stage_repository, google_sheets_service = (
        make_executor()
    )
    message = make_message("Até R$300")
    patient_stage_repository.get_context = AsyncMock(
        return_value=PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            area="Psicoterapia",
        )
    )

    await executor.sheets_register_patient(message)

    google_sheets_service.register_patient.assert_called_once()
    patient_sheet = google_sheets_service.register_patient.call_args.args[0]
    assert patient_sheet.name == "Maria"
    assert patient_sheet.phone == message.user_id
    assert patient_sheet.area == "Psicoterapia"


@pytest.mark.asyncio
async def test_sheets_register_patient_swallows_service_errors() -> None:
    executor, _, _, _, patient_stage_repository, google_sheets_service = (
        make_executor()
    )
    message = make_message("Até R$300")
    patient_stage_repository.get_context = AsyncMock(
        return_value=PatientStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            area="Psicoterapia",
        )
    )
    google_sheets_service.register_patient.side_effect = GoogleSheetsServiceError(
        "boom"
    )

    result = await executor.sheets_register_patient(message)

    assert result == ""


@pytest.mark.asyncio
async def test_sheets_register_professional_defaults_to_inactive() -> None:
    executor, stage_repository, _, _, _, google_sheets_service = make_executor()
    message = make_message()
    stage_repository.get_context = AsyncMock(
        return_value=ProfessionalStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            area="Psicoterapia",
        )
    )

    await executor.sheets_register_professional(message)

    google_sheets_service.register_professional.assert_called_once()
    professional_sheet = google_sheets_service.register_professional.call_args.args[0]
    assert professional_sheet.name == "Maria"
    assert professional_sheet.area == "Psicoterapia"
    assert professional_sheet.phone == message.user_id
    assert professional_sheet.active is False


@pytest.mark.asyncio
async def test_sheets_register_professional_swallows_service_errors() -> None:
    executor, stage_repository, _, _, _, google_sheets_service = make_executor()
    message = make_message()
    stage_repository.get_context = AsyncMock(
        return_value=ProfessionalStageContext(
            user_id=message.user_id,
            chat_id=message.chat_id,
            channel=message.channel,
            name="Maria",
            area="Psicoterapia",
        )
    )
    google_sheets_service.register_professional.side_effect = (
        GoogleSheetsServiceError("boom")
    )

    result = await executor.sheets_register_professional(message)

    assert result == ""
