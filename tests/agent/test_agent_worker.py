from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.action_executor import ActionResult
from app.agent.agent import AgentWorker
from app.agent.chat_flow import ChatFlow, Node, Transition, TransitionAction, normalize_text
from app.domain.enum.channels import Channel
from app.domain.enum.chatbot_flow import InputType, NodeType
from app.domain.message import Message
from app.domain.redis.chat import ChatContext
from app.repository.redis.chatbot_flow_cache import StaticFlowProvider


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
    mock_actions: bool = True,
) -> AgentWorker:
    active_flow = flow or basic_flow()
    worker = AgentWorker(
        ctx=MagicMock(),
        inbound=MagicMock(),
        outbound=MagicMock(),
        chat_repository=cast(Any, chat_repository),
        professional_repository=MagicMock(),
        professional_stage_repository=MagicMock(),
        person_repository=MagicMock(),
        patient_repository=MagicMock(),
        patient_stage_repository=MagicMock(),
        outbox_repository=MagicMock(),
        faq_knowledge_repository=MagicMock(),
        faq_session_repository=MagicMock(),
        flow_provider=StaticFlowProvider(active_flow),
    )
    if mock_actions:
        cast(Any, worker.action_executor).run = AsyncMock(return_value="")
    return worker


def make_message(
    content: str | None,
    *,
    media: str | None = None,
) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=None,
        user_id="user-1",
        chat_id="chat-1",
        content=content,
        media=media,
    )


def build_flow(data: dict[str, Any]) -> ChatFlow:
    nodes: dict[str, Node] = {}
    for node_position, (key, raw_node) in enumerate(data["nodes"].items()):
        transitions: list[Transition] = []
        buttons = raw_node.get("buttons", [])
        used_buttons: set[str] = set()
        position = 0
        for raw_transition in raw_node.get("transitions", []):
            conditions = raw_transition.get("conditions", [])
            if conditions:
                specs = [(InputType.TEXT, condition) for condition in conditions]
            else:
                input_name = raw_node.get("input")
                fallback_types = {
                    "Imagem ou documento": [InputType.IMAGE, InputType.DOCUMENT],
                    "Vídeo": [InputType.VIDEO],
                    "Texto": [InputType.TEXT],
                }.get(input_name, [InputType.AUTO])
                specs = [(input_type, None) for input_type in fallback_types]

            for input_type, expected_value in specs:
                button_label = None
                if expected_value is not None:
                    for button in buttons:
                        if (
                            button not in used_buttons
                            and normalize_text(button) == normalize_text(expected_value)
                        ):
                            button_label = button
                            used_buttons.add(button)
                            break
                transitions.append(
                    Transition(
                        input_type=input_type,
                        expected_value=expected_value,
                        button_label=button_label,
                        target=raw_transition["target"],
                        position=position,
                        actions=[
                            TransitionAction(action_key=action)
                            for action in raw_node.get("actions", [])
                        ],
                    )
                )
                position += 1

        node_type = (
            NodeType.START
            if key == "start"
            else NodeType.END
            if raw_node.get("end")
            else NodeType.MESSAGE
        )
        nodes[key] = Node(
            key=key,
            type=node_type,
            title=key,
            description=raw_node.get("description"),
            message=raw_node["message"],
            position=node_position,
            transitions=transitions,
        )
    return ChatFlow(
        nodes=nodes,
        input_error_messages={
            InputType.IMAGE: "Envie uma imagem.",
            InputType.DOCUMENT: "Envie um documento.",
            InputType.VIDEO: "Envie um vídeo.",
        },
    )


def basic_flow() -> ChatFlow:
    return build_flow({"nodes": {
        "start": {
            "message": "start",
            "buttons": ["Sou profissional"],
            "transitions": [{"target": "profissional_start", "conditions": ["sou profissional"]}],
        },
        "profissional_start": {"message": "professional"},
    }})


def media_flow() -> ChatFlow:
    return build_flow(
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


def video_flow() -> ChatFlow:
    flow = media_flow()
    upload = flow.get("upload")
    assert upload is not None
    upload.transitions = [
        Transition(
            input_type=InputType.VIDEO,
            target="done",
            position=0,
        )
    ]
    return flow


@pytest.mark.asyncio
async def test_first_message_creates_context_and_returns_start() -> None:
    chat_repository = FakeChatRepository()
    flow = basic_flow()
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
    flow = basic_flow()
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
    flow = basic_flow()
    worker = make_worker(chat_repository, flow=flow)
    start_node = flow.get("start")
    assert start_node is not None

    response = await worker._process_message(make_message("Oi"))

    assert response.content == start_node.message
    assert response.buttons == start_node.buttons
    assert chat_repository.updated_state is None


@pytest.mark.asyncio
async def test_reset_returns_to_start_and_updates_context() -> None:
    flow = basic_flow()
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

    await worker._process_message(make_message(None, media="media/image/image-id.jpg"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_node_accepts_document() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=media_flow())

    await worker._process_message(
        make_message(None, media="media/document/document-id.pdf")
    )

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_node_accepts_video() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=video_flow())

    await worker._process_message(
        make_message(None, media="media/video/qualification.mp4")
    )

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_node_blocks_free_text_without_video() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=video_flow())

    response = await worker._process_message(make_message("texto livre"))

    assert response.content == "Envie um vídeo."
    assert chat_repository.updated_state is None
    worker.action_executor.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_video_node_allows_explicit_button_without_video() -> None:
    chat_repository = FakeChatRepository(state="upload")
    flow = video_flow()
    upload = flow.get("upload")
    assert upload is not None
    upload.transitions = [
        Transition(
            input_type=InputType.TEXT,
            expected_value="nao tenho interesse",
            button_label="Não tenho interesse",
            target="done",
            position=0,
        ),
        Transition(
            input_type=InputType.VIDEO,
            target="done",
            position=1,
        ),
    ]
    worker = make_worker(chat_repository, flow=flow)

    await worker._process_message(make_message("Não tenho interesse"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "media",
    ["media/image/profile.jpg", "media/document/curriculum.pdf"],
)
async def test_video_node_rejects_other_media_types(media: str) -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=video_flow())

    response = await worker._process_message(make_message(None, media=media))

    assert response.content == "Envie um vídeo."
    assert chat_repository.updated_state is None
    worker.action_executor.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_node_allows_explicit_text_transition_without_media() -> None:
    chat_repository = FakeChatRepository(state="upload")
    worker = make_worker(chat_repository, flow=media_flow())

    await worker._process_message(make_message("skip"))

    assert chat_repository.updated_state == "done"
    worker.action_executor.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_action_can_override_static_flow_transition() -> None:
    chat_repository = FakeChatRepository(state="route")
    flow = build_flow(
        {
            "nodes": {
                "start": {"message": "start"},
                "route": {
                    "message": "route",
                    "actions": ["route_patient"],
                    "transitions": [{"target": "first", "conditions": []}],
                },
                "first": {"message": "first"},
                "returning": {"message": "returning"},
            }
        }
    )
    worker = make_worker(chat_repository, flow=flow)
    cast(Any, worker.action_executor).run = AsyncMock(
        return_value=ActionResult(next_node="returning")
    )

    response = await worker._process_message(make_message("Atendimento normal"))

    assert response.content == "returning"
    assert chat_repository.updated_state == "returning"
