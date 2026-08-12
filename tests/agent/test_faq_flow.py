from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.faq_flow import FAQ_NOT_FOUND_MESSAGE, FaqFlow
from app.domain.enum.channels import Channel
from app.domain.enum.faq_answer_status import FaqAnswerStatus
from app.domain.message import Message
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeCandidate
from app.services.openai_service import (
    OpenAIEmbeddingResult,
    OpenAIFaqSelectionResult,
)


def _message() -> Message:
    return Message(
        message_id=10,
        history_id=100,
        channel=Channel.WHATSAPP,
        created_at=None,
        user_id="5511999999999",
        chat_id="5511999999999",
        content="Como funciona o atendimento?",
    )


def _flow_dependencies() -> tuple[
    FaqFlow,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    person_repository = MagicMock()
    person_repository.get_by_phone_number_and_channel.return_value = MagicMock(id=1)
    session_repository = MagicMock()
    session_repository.get_or_create_active.return_value = MagicMock(id=2)
    knowledge_repository = MagicMock()
    openai_service = MagicMock()
    openai_service.generate_embedding = AsyncMock(
        return_value=OpenAIEmbeddingResult(
            embedding=[0.1, 0.2],
            model="embedding-model",
            input_tokens=4,
            latency_ms=10,
            raw_response=object(),
        )
    )
    openai_service.select_faq_answer = AsyncMock()
    flow = FaqFlow(
        person_repository=person_repository,
        session_repository=session_repository,
        knowledge_repository=knowledge_repository,
        openai_service=openai_service,
        retrieval_limit=5,
    )
    return flow, session_repository, knowledge_repository, openai_service


@pytest.mark.asyncio
async def test_process_returns_selected_answer_and_records_interaction() -> None:
    flow, session_repository, knowledge_repository, openai_service = (
        _flow_dependencies()
    )
    candidate = FaqKnowledgeCandidate(
        entry_id=7,
        question="Como funciona?",
        answer="O atendimento acontece por videochamada.",
        similarity_score=0.93,
    )
    knowledge_repository.find_similar.return_value = [candidate]
    openai_service.select_faq_answer.return_value = OpenAIFaqSelectionResult(
        selected_entry_id=7,
        response_id="resp_1",
        model="response-model",
        input_tokens=20,
        output_tokens=3,
        latency_ms=30,
        raw_response=object(),
    )
    session_repository.record_interaction.return_value = MagicMock(
        id=9,
        session_id=2,
        selected_entry_id=7,
        question_number=1,
    )

    result = await flow.process(_message())

    assert result.content == "O atendimento acontece por videochamada."
    assert result.selected_entry_id == 7
    knowledge_repository.find_similar.assert_called_once_with(
        embedding=[0.1, 0.2],
        embedding_model="embedding-model",
        limit=5,
    )
    recorded = session_repository.record_interaction.call_args.kwargs
    assert recorded["selected_entry_id"] == 7
    assert recorded["answer_status"] is None
    assert recorded["similarity_score"] == 0.93
    assert recorded["input_tokens"] == 24
    assert recorded["output_tokens"] == 3


@pytest.mark.asyncio
async def test_process_skips_selection_when_retrieval_has_no_candidates() -> None:
    flow, session_repository, knowledge_repository, openai_service = (
        _flow_dependencies()
    )
    knowledge_repository.find_similar.return_value = []
    session_repository.record_interaction.return_value = MagicMock(
        id=9,
        session_id=2,
        selected_entry_id=None,
        question_number=1,
    )

    result = await flow.process(_message())

    assert result.content == FAQ_NOT_FOUND_MESSAGE
    openai_service.select_faq_answer.assert_not_awaited()
    recorded = session_repository.record_interaction.call_args.kwargs
    assert recorded["answer_status"] == FaqAnswerStatus.NOT_FOUND
    assert recorded["input_tokens"] == 4
    assert recorded["output_tokens"] == 0


@pytest.mark.asyncio
async def test_process_treats_unknown_selected_id_as_not_found() -> None:
    flow, session_repository, knowledge_repository, openai_service = (
        _flow_dependencies()
    )
    knowledge_repository.find_similar.return_value = [
        FaqKnowledgeCandidate(
            entry_id=7,
            question="Referência",
            answer="Resposta",
            similarity_score=0.8,
        )
    ]
    openai_service.select_faq_answer.return_value = OpenAIFaqSelectionResult(
        selected_entry_id=999,
        response_id="resp_1",
        model="response-model",
        input_tokens=20,
        output_tokens=3,
        latency_ms=30,
        raw_response=object(),
    )
    session_repository.record_interaction.return_value = MagicMock(
        id=9,
        session_id=2,
        selected_entry_id=None,
        question_number=1,
    )

    result = await flow.process(_message())

    assert result.content == FAQ_NOT_FOUND_MESSAGE
    recorded = session_repository.record_interaction.call_args.kwargs
    assert recorded["selected_entry_id"] is None
    assert recorded["answer_status"] == FaqAnswerStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_process_requires_persisted_message_history() -> None:
    flow, _, _, _ = _flow_dependencies()
    message = _message().model_copy(update={"history_id": None})

    with pytest.raises(ValueError, match="history id"):
        await flow.process(message)
