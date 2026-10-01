from datetime import datetime

import pytest
from pydantic import ValidationError

from app.agent.chat_flow import ChatFlow, Node, Transition, TransitionAction
from app.domain.enum.channels import Channel
from app.domain.enum.chatbot_flow import InputType, NodeType
from app.domain.message import Message


def message(content: str | None = None, media: str | None = None) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime(2026, 1, 1),
        user_id="user",
        chat_id="chat",
        content=content,
        media=media,
    )


def flow_with(transition: Transition) -> ChatFlow:
    return ChatFlow(
        nodes={
            "start": Node(
                key="start",
                type=NodeType.START,
                title="Início",
                message="Início",
                position=0,
                transitions=[transition],
            ),
            "end": Node(
                key="end",
                type=NodeType.END,
                title="Fim",
                message="Fim",
                position=1,
            ),
        }
    )


def test_flow_does_not_require_a_single_reserved_start_key() -> None:
    flow = ChatFlow(
        nodes={
            "entrada_paciente": Node(
                key="entrada_paciente",
                type=NodeType.START,
                title="Início",
                message="Início",
                position=0,
            ),
            "entrada_profissional": Node(
                key="entrada_profissional",
                type=NodeType.START,
                title="Início profissional",
                message="Início profissional",
                position=1,
            ),
        }
    )

    assert set(flow.nodes) == {"entrada_paciente", "entrada_profissional"}


def test_flow_rejects_missing_transition_target() -> None:
    with pytest.raises(ValidationError, match="missing transition"):
        ChatFlow(
            nodes={
                "start": Node(
                    key="start",
                    type=NodeType.START,
                    title="Início",
                    message="Início",
                    position=0,
                    transitions=[
                        Transition(
                            input_type=InputType.AUTO,
                            target="missing",
                            position=0,
                        )
                    ],
                )
            }
        )


def test_text_expected_value_ignores_case_and_accents() -> None:
    transition = Transition(
        input_type=InputType.TEXT,
        expected_value="renovacao por pix",
        target="end",
        position=0,
    )

    assert transition.matches(message("Renovação por Pix"))


def test_action_config_routes_third_faq_question() -> None:
    transition = Transition(
        input_type=InputType.TEXT,
        target="faq_resposta",
        position=0,
        actions=[
            TransitionAction(
                action_key="faq_process_question",
                config={
                    "config_type": "action_transition",
                    "source": {
                        "type": "action_result",
                        "field": "question_count",
                    },
                    "operator": "gte",
                    "value": 3,
                    "target_node_key": "faq_resposta_com_atendimento",
                },
            )
        ],
    )

    assert transition.target_for({"question_count": 2}) == "faq_resposta"
    assert transition.target_for({"question_count": 3}) == (
        "faq_resposta_com_atendimento"
    )


@pytest.mark.parametrize(
    ("input_type", "content", "accepted"),
    [
        (InputType.EMAIL, "maria@example.com", True),
        (InputType.EMAIL, "maria@", False),
        (InputType.DATE, "29/02/2024", True),
        (InputType.DATE, "31/02/2024", False),
        (InputType.NUMBER, "1.234,56", True),
        (InputType.NUMBER, "abc", False),
        (InputType.TEXT, "resposta", True),
        (InputType.TEXT, "", False),
        (InputType.AUTO, None, True),
    ],
)
def test_validates_textual_input_types(
    input_type: InputType,
    content: str | None,
    accepted: bool,
) -> None:
    transition = Transition(input_type=input_type, target="end", position=0)

    assert transition.accepts_input(message(content)) is accepted


@pytest.mark.parametrize(
    ("input_type", "media", "accepted"),
    [
        (InputType.IMAGE, "media/image/photo.jpg", True),
        (InputType.DOCUMENT, "media/document/file.pdf", True),
        (InputType.VIDEO, "media/video/file.mp4", True),
        (InputType.VIDEO, "media/image/photo.jpg", False),
    ],
)
def test_validates_media_input_types(
    input_type: InputType,
    media: str,
    accepted: bool,
) -> None:
    transition = Transition(input_type=input_type, target="end", position=0)

    assert transition.accepts_input(message(media=media)) is accepted


def test_buttons_are_derived_from_ordered_transitions_without_alias_duplicates() -> None:
    node = Node(
        key="start",
        type=NodeType.START,
        title="Início",
        message="Início",
        position=0,
        transitions=[
            Transition(
                input_type=InputType.TEXT,
                expected_value="email",
                button_label="E-mail",
                target="end",
                position=0,
            ),
            Transition(
                input_type=InputType.TEXT,
                expected_value="e-mail",
                target="end",
                position=1,
            ),
        ],
    )

    assert node.buttons == ["E-mail"]


def test_combined_media_error_message() -> None:
    flow = flow_with(
        Transition(input_type=InputType.IMAGE, target="end", position=0)
    )
    start = flow.get("start")
    assert start is not None
    start.transitions.append(
        Transition(input_type=InputType.DOCUMENT, target="end", position=1)
    )

    assert flow.error_message(start, message("texto")) == (
        "Você deve enviar uma imagem ou um documento."
    )


def test_combined_media_uses_configured_message_from_first_transition() -> None:
    flow = flow_with(
        Transition(input_type=InputType.IMAGE, target="end", position=0)
    )
    start = flow.get("start")
    assert start is not None
    start.transitions.append(
        Transition(input_type=InputType.DOCUMENT, target="end", position=1)
    )
    flow.input_error_messages = {
        InputType.IMAGE: "Envie a imagem configurada.",
        InputType.DOCUMENT: "Envie o documento configurado.",
    }

    assert flow.error_message(start, message("texto")) == "Envie a imagem configurada."
