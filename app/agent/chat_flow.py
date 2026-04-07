import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
DEFAULT_FLOW_PATH = Path(__file__).with_name("flow.json")


def _normalize_text(value: str) -> str:
    return value.strip().lower()


class Transition(BaseModel):
    target: str
    conditions: list[str] = Field(default_factory=list)

    def matches(self, content: str) -> bool:
        if not self.conditions:
            return True

        normalized_content = _normalize_text(content)
        normalized_conditions = {_normalize_text(condition) for condition in self.conditions}
        return normalized_content in normalized_conditions


class Node(BaseModel):
    id: str
    description: str | None = None
    message: str
    end: bool = False
    transitions: list[Transition] = Field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def next_transition(self, content: str) -> Transition | None:
        for transition in self.transitions:
            if transition.matches(content):
                return transition
        return None


class ChatFlow(BaseModel):
    nodes: dict[str, Node]

    @classmethod
    def from_json(cls, payload: str) -> "ChatFlow":
        """Build a ChatFlow from a JSON payload string."""
        data = json.loads(payload)
        return cls.from_data(data)

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_FLOW_PATH) -> "ChatFlow":
        """Load a ChatFlow from a JSON file."""
        flow_path = Path(path)

        with flow_path.open("r", encoding="utf-8") as flow_file:
            data = json.load(flow_file)

        return cls.from_data(data)

    @classmethod
    def from_data(cls, data: Any) -> "ChatFlow":
        """Validate and normalize the raw JSON data into a ChatFlow."""
        if not isinstance(data, dict):
            raise ValueError("Flow JSON must be an object with a 'nodes' property.")

        nodes_data = data.get("nodes")
        if not isinstance(nodes_data, dict):
            raise ValueError("Flow JSON must contain a 'nodes' object.")

        nodes: dict[str, Node] = {}

        for node_id, node_data in nodes_data.items():
            if not isinstance(node_data, dict):
                raise ValueError(f"Flow node '{node_id}' must be a JSON object.")

            try:
                nodes[node_id] = Node(id=node_id, **node_data)
            except Exception as err:
                logger.error(f"Error validating flow node '{node_id}': {err}")
                raise ValueError(f"Invalid flow node '{node_id}': {err}") from err

        if "start" not in nodes:
            raise ValueError("Flow JSON must contain a 'start' node.")

        return cls(nodes=nodes)

    def get(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def keys(self) -> list[str]:
        return list(self.nodes.keys())

    def resolve_next_node(self, node_id: str, content: str) -> Node | None:
        node = self.get(node_id)
        if node is None:
            return None

        transition = node.next_transition(content)
        if transition is None:
            return None

        return self.get(transition.target)
