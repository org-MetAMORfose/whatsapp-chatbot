"""Read the published chatbot graph in one consistent SQL snapshot."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.chat_flow import ChatFlow, Node, Transition, TransitionAction
from app.domain.db.chatbot_flow_model import (
    FlowInputErrorMessageModel,
    FlowNodeModel,
    FlowRevisionModel,
    FlowTransitionActionModel,
    FlowTransitionModel,
)
from app.domain.enum.chatbot_flow import InputType, NodeType


class ChatFlowRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def load(self) -> tuple[int, ChatFlow]:
        with self._session_factory() as session, session.begin():
            revision = session.scalar(
                select(FlowRevisionModel.version).where(FlowRevisionModel.id == 1)
            )
            if revision is None:
                raise RuntimeError("Chatbot flow revision is missing")

            node_rows = session.scalars(
                select(FlowNodeModel).order_by(FlowNodeModel.position, FlowNodeModel.id)
            ).all()
            transition_rows = session.scalars(
                select(FlowTransitionModel).order_by(
                    FlowTransitionModel.node_id,
                    FlowTransitionModel.position,
                    FlowTransitionModel.id,
                )
            ).all()
            action_rows = session.scalars(
                select(FlowTransitionActionModel).order_by(
                    FlowTransitionActionModel.transition_id,
                    FlowTransitionActionModel.id,
                )
            ).all()
            error_rows = session.scalars(
                select(FlowInputErrorMessageModel)
            ).all()

        keys_by_id = {row.id: row.key for row in node_rows}
        actions_by_transition: dict[int, list[TransitionAction]] = {}
        for action_row in action_rows:
            actions_by_transition.setdefault(action_row.transition_id, []).append(
                TransitionAction(
                    action_key=action_row.action_key,
                    config=action_row.config,
                    is_required=action_row.is_required,
                )
            )

        transitions_by_node: dict[int, list[Transition]] = {}
        for transition_row in transition_rows:
            target = keys_by_id.get(transition_row.next_node_id)
            if target is None:
                raise ValueError(
                    f"Transition {transition_row.id} references unknown node {transition_row.next_node_id}"
                )
            transitions_by_node.setdefault(transition_row.node_id, []).append(
                Transition(
                    input_type=InputType(transition_row.input_type),
                    expected_value=transition_row.expected_value,
                    button_label=transition_row.button_label,
                    target=target,
                    position=transition_row.position,
                    actions=actions_by_transition.get(transition_row.id, []),
                )
            )

        nodes = {
            row.key: Node(
                key=row.key,
                type=NodeType(row.type),
                title=row.title,
                description=row.description,
                message=row.message,
                position=row.position,
                transitions=transitions_by_node.get(row.id, []),
            )
            for row in node_rows
        }
        errors = {
            InputType(row.input_type): row.message
            for row in error_rows
        }
        return revision, ChatFlow(nodes=nodes, input_error_messages=errors)
