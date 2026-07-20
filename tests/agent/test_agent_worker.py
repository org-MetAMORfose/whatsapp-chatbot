from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.agent import AgentWorker
from app.agent.chat_flow import ChatFlow
from app.domain.chat import ChatContext
from app.domain.enum.channels import Channel
from app.domain.message import Message


class FakeChatRepository:
    def __init__(self, state: str | None = None) -> None:
        self.context: ChatContext | None = None
        self.created_state: str | None = None
        self.updated_state: str | None = None
        self.deleted = False

        if state is not None:
            self.context = ChatContext(
                user_id="user-1",
                channel=Channel.WHATSAPP,
                state=state,
            )

    async def get_context(
        self,
        user_id: str,
        channel: Channel,
    ) -> ChatContext | None:
        return self.context

    async def create_context(
        self,
        user_id: str,
        channel: Channel,
        state: str,
    ) -> ChatContext:
        self.created_state = state
        self.context = ChatContext(
            user_id=user_id,
            channel=channel,
            state=state,
        )
        return self.context

    async def update_context(
        self,
        message: Message,
        state: str,
    ) -> ChatContext:
        self.updated_state = state
        if self.context is None:
            self.context = ChatContext(
                user_id=message.user_id,
                channel=message.channel,
                state=state,
            )
        else:
            self.context.state = state
        return self.context

    async def delete_context(
        self,
        user_id: str,
        channel: Channel,
    ) -> bool:
        self.deleted = True
        self.context = None
        return True


def make_worker(
    chat_repository: FakeChatRepository,
    *,
    flow: ChatFlow | None = None,
) -> AgentWorker:
    worker = AgentWorker(
        ctx=MagicMock(),
        inbound=MagicMock(),
        outbound=MagicMock(),
        chat_repository=cast(Any, chat_repository),
        professional_repository=MagicMock(),
        professional_stage_repository=MagicMock(),
        person_repository=MagicMock(),
        patient_stage_repository=MagicMock(),
        google_sheets_service=MagicMock(),
    )
    if flow is not None:
        worker.flow = flow
    cast(Any, worker.action_executor).run = AsyncMock(return_value="")
    return worker


def make_message(
    content: str | None,
    *,
    image: str | None = None,
    document: str | None = None,
) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=None,
        user_id="user-1",
        chat_id="chat-1",
        content=content,
        image=image,
        document=document,
    )


def media_flow() -> ChatFlow:
    return ChatFlow.from_data(
        {
            "nodes": {
                "start": {
                    "message": "start",
                    "transitions": [
                        {
                            "target": "upload",
                            "conditions": [],
                        }
                    ],
                },
                "upload": {
                    "message": "upload",
                    "input": "Imagem ou documento",
                    "buttons": ["Skip"],
                    "transitions": [
                        {
                            "target": "done",
                            "conditions": ["skip"],
                        },
                        {
                            "target": "done",
                            "conditions": [],
                        },
                    ],
                },
                "done": {
                    "message": "done",
                    "transitions": [
                        {
                            "target": "end",
                            "conditions": [],
                        }
                    ],
                },
                "end": {
                    "message": "end",
                    "end": True,
                },
            }
        }
    )


@pytest.mark.asyncio
async def test_first_message_creates_context_and_returns_start() -> None:
    chat_repository = FakeChatRepository()
    flow = ChatFlow.from_file()
    worker = make_worker(chat_repository, flow=flow)
    start_node = flow.get("start")
    assert start_node is not None

    response = await worker._process_message(make_message("oi"))

    assert response.content == start_node.message
    assert response.buttons == start_node.buttons
    assert chat_repository.created_state == "start"


@pytest.mark.asyncio
async def test_first_message_can_transition_from_start() -> None:
    chat_repository = FakeChatRepository()
    flow = ChatFlow.from_file()
    worker = make_worker(chat_repository, flow=flow)
    professional_node = flow.get("profissional_start")
    assert professional_node is not None

    response = await worker._process_message(make_message("Sou profissional"))

    assert response.content == professional_node.message
    assert response.buttons == professional_node.buttons
    assert chat_repository.created_state == "start"
    assert chat_repository.updated_state == "profissional_start"


@pytest.mark.asyncio
async def test_invalid_response_repeats_current_node() -> None:
    chat_repository = FakeChatRepository(state="start")
    flow = ChatFlow.from_file()
    worker = make_worker(chat_repository, flow=flow)
    start_node = flow.get("start")
    assert start_node is not None

    response = await worker._process_message(make_message("Oi"))

    assert response.content == start_node.message
    assert response.buttons == start_node.buttons
    assert chat_repository.updated_state is None


@pytest.mark.asyncio
async def test_reset_returns_to_start_and_updates_context() -> None:
    flow = ChatFlow.from_file()
    non_start_state = next(node_id for node_id in flow.nodes if node_id != "start")
    chat_repository = FakeChatRepository(state=non_start_state)
    worker = make_worker(chat_repository, flow=flow)
    start_node = flow.get("start")
    assert start_node is not None

    response = await worker._process_message(make_message("reset"))

    assert response.content == start_node.message
    assert response.buttons == start_node.buttons
    assert chat_repository.updated_state == "start"
    assert chat_repository.context is not None
    assert chat_repository.context.state == "start"


@pytest.mark.asyncio
async def test_media_node_blocks_text_without_media() -> None:
    chat_repository = FakeChatRepository(state="upload")
    flow = media_flow()
    worker = make_worker(chat_repository, flow=flow)
    upload_node = flow.get("upload")
    assert upload_node is not None

    response = await worker._process_message(make_message("text"))

    assert response.buttons == upload_node.buttons
    assert chat_repository.context is not None
    assert chat_repository.context.state == "upload"
    assert chat_repository.updated_state is None
    worker.action_executor.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_node_accepts_image() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=media_flow())

    await worker._process_message(make_message(None, image="image-id"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_node_accepts_document() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=media_flow())

    await worker._process_message(make_message(None, document="document-id"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_node_allows_explicit_text_transition_without_media() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=media_flow())

    await worker._process_message(make_message("skip"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()
