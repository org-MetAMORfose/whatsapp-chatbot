import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)
DEFAULT_FLOW_PATH = Path(__file__).with_name("flow.json")


class Node(BaseModel):
    id: str
    message: str
    yes: str | None = None
    no: str | None = None
    next: str | None = None
    end: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


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
