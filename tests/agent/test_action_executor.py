from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.action_executor import ActionExecutor
from app.domain.enum.channels import Channel
from app.domain.enum.chat_mode import ChatMode
from app.domain.enum.chat_state import ChatState
from app.domain.message import Message
from app.domain.professional_stage import ProfessionalStageContext


def make_message(content: str | None = None) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime(2026, 6, 22),
        user_id="5511999999999",
        chat_id="chat-1",
        content=content,
    )


def make_executor() -> tuple[ActionExecutor, MagicMock, MagicMock, MagicMock]:
    stage_repository = MagicMock()
    professional_repository = MagicMock()
    person_repository = MagicMock()
    executor = ActionExecutor(
        stage_repository,
        professional_repository,
        person_repository,
    )
    return (
        executor,
        stage_repository,
        professional_repository,
        person_repository,
    )


@pytest.mark.asyncio
async def test_set_chat_state_delegates_priority_check_to_repository() -> None:
    executor, _, _, person_repository = make_executor()
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
    executor, _, _, person_repository = make_executor()

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
    executor, _, _, person_repository = make_executor()

    await executor.postgres_set_new_patient_state(
        make_message("Tenho dúvida"),
    )
    person_repository.update_chat_state_by_contact.assert_not_called()

    await executor.postgres_set_new_patient_state(
        make_message("Quero sessão"),
    )
    person_repository.update_chat_state_by_contact.assert_called_once()


@pytest.mark.asyncio
async def test_manual_chat_mode_is_enabled_when_user_selects_duvidas() -> None:
    executor, _, _, person_repository = make_executor()

    await executor.postgres_set_manual_chat_mode(make_message("Dúvidas"))

    person_repository.update_chat_mode_by_contact.assert_called_once_with(
        phone_number="5511999999999",
        channel=Channel.WHATSAPP,
        chat_mode=ChatMode.MANUAL,
    )


@pytest.mark.asyncio
async def test_register_professional_application_from_stage() -> None:
    executor, stage_repository, professional_repository, person_repository = (
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
