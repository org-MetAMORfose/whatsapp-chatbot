"""Validated in-memory representation of the database-backed chatbot flow."""

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.enum.chatbot_flow import InputType, NodeType
from app.domain.message import Message
from app.services.s3_media_service import S3MediaService

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DATE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(character for character in normalized if not unicodedata.combining(character))


class ActionTransitionSource(BaseModel):
    type: Literal["action_result"]
    field: str = Field(min_length=1)


class ActionTransitionConfig(BaseModel):
    config_type: Literal["action_transition"]
    source: ActionTransitionSource
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte"]
    value: Any
    target_node_key: str = Field(min_length=1)


class TransitionAction(BaseModel):
    id: int | None = None
    action_key: str
    config: dict[str, Any] | None = None
    is_required: bool = True
    depends_on_ids: list[int] = Field(default_factory=list)


class Transition(BaseModel):
    id: int | None = None
    input_type: InputType
    expected_value: str | None = None
    button_label: str | None = None
    target: str
    position: int
    actions: list[TransitionAction] = Field(default_factory=list)

    def accepts_input(self, message: Message) -> bool:
        if self.input_type == InputType.AUTO:
            return True

        if self.input_type in {InputType.IMAGE, InputType.DOCUMENT, InputType.VIDEO}:
            if message.media is None:
                return False
            try:
                media_type = S3MediaService.get_media_type(message.media)
            except ValueError:
                return False
            expected_media_type = {
                InputType.IMAGE: "image",
                InputType.DOCUMENT: "document",
                InputType.VIDEO: "video",
            }[self.input_type]
            return media_type == expected_media_type

        content = (message.content or "").strip()
        if not content:
            return False
        if self.input_type == InputType.TEXT:
            return True
        if self.input_type == InputType.EMAIL:
            return EMAIL_PATTERN.fullmatch(content) is not None
        if self.input_type == InputType.DATE:
            return _valid_date(content)
        if self.input_type == InputType.NUMBER:
            return _valid_number(content)
        return False

    def matches(self, message: Message) -> bool:
        if not self.accepts_input(message):
            return False
        if self.expected_value is None:
            return True
        return normalize_text(message.content or "") == normalize_text(self.expected_value)

    def target_for(self, action_data: dict[str, Any]) -> str:
        for action in self.actions:
            if action.config is None:
                continue
            config = ActionTransitionConfig.model_validate(action.config)
            actual = action_data.get(config.source.field)
            if actual is not None and _compare(actual, config.operator, config.value):
                return config.target_node_key
        return self.target


class Node(BaseModel):
    id: int | None = None
    key: str
    type: NodeType
    title: str
    description: str | None = None
    message: str
    position: int
    transitions: list[Transition] = Field(default_factory=list)

    @property
    def end(self) -> bool:
        return self.type == NodeType.END

    @property
    def buttons(self) -> list[str] | None:
        labels: list[str] = []
        for transition in self.transitions:
            label = transition.button_label
            if label is not None and label not in labels:
                labels.append(label)
        return labels or None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def next_transition(self, message: Message) -> Transition | None:
        return next((transition for transition in self.transitions if transition.matches(message)), None)

    def input_error_type(self, message: Message) -> InputType | None:
        fallback_types = {
            transition.input_type for transition in self.transitions if transition.expected_value is None and transition.input_type != InputType.AUTO
        }
        if not fallback_types:
            return None
        if any(transition.expected_value is None and transition.accepts_input(message) for transition in self.transitions):
            return None

        media_types = fallback_types & {InputType.IMAGE, InputType.DOCUMENT, InputType.VIDEO}
        if media_types:
            return sorted(media_types, key=lambda item: item.value)[0]

        for input_type in (InputType.DATE, InputType.EMAIL, InputType.NUMBER, InputType.TEXT):
            if input_type in fallback_types:
                return input_type
        return None


class ChatFlow(BaseModel):
    nodes: dict[str, Node]
    input_error_messages: dict[InputType, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_graph(self) -> "ChatFlow":
        missing_targets = [
            (node.key, transition.target) for node in self.nodes.values() for transition in node.transitions if transition.target not in self.nodes
        ]
        if missing_targets:
            raise ValueError(f"Flow contains missing transition targets: {missing_targets}")

        missing_config_targets: list[tuple[str, str]] = []
        for node in self.nodes.values():
            for transition in node.transitions:
                for action in transition.actions:
                    if action.config is None:
                        continue
                    config = ActionTransitionConfig.model_validate(action.config)
                    if config.target_node_key not in self.nodes:
                        missing_config_targets.append((node.key, config.target_node_key))
        if missing_config_targets:
            raise ValueError(f"Flow contains missing action targets: {missing_config_targets}")

        for node in self.nodes.values():
            positions = [transition.position for transition in node.transitions]
            if len(positions) != len(set(positions)):
                raise ValueError(f"Flow node '{node.key}' contains duplicate transition positions")
        return self

    @classmethod
    def from_json(cls, payload: str) -> "ChatFlow":
        return cls.model_validate(json.loads(payload))

    def get(self, node_key: str) -> Node | None:
        return self.nodes.get(node_key)

    def keys(self) -> list[str]:
        return list(self.nodes)

    def error_message(self, node: Node, message: Message) -> str | None:
        input_type = node.input_error_type(message)
        if input_type is None:
            return None

        fallback_types = {transition.input_type for transition in node.transitions if transition.expected_value is None}
        if {InputType.IMAGE, InputType.DOCUMENT}.issubset(fallback_types):
            return "Você deve enviar uma imagem ou um documento."
        return self.input_error_messages.get(
            input_type,
            "Não foi possível validar sua resposta. Tente novamente.",
        )


def _valid_date(content: str) -> bool:
    if DATE_PATTERN.fullmatch(content) is None:
        return False
    try:
        parsed = datetime.strptime(content, "%d/%m/%Y").date()
    except ValueError:
        return False
    return parsed <= date.today()


def _valid_number(content: str) -> bool:
    compact = content.strip().replace(" ", "")
    candidates = [compact]
    if "," in compact:
        candidates.append(compact.replace(".", "").replace(",", "."))
    for candidate in candidates:
        try:
            Decimal(candidate)
            return True
        except InvalidOperation:
            continue
    return False


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    try:
        if operator == "eq":
            return bool(actual == expected)
        if operator == "neq":
            return bool(actual != expected)
        if operator == "gt":
            return bool(actual > expected)
        if operator == "gte":
            return bool(actual >= expected)
        if operator == "lt":
            return bool(actual < expected)
        if operator == "lte":
            return bool(actual <= expected)
    except TypeError:
        return False
    return False
