from typing import Any

from .chat_flow import ChatFlow, Node, Transition

__all__ = ["AgentWorker", "ChatFlow", "Node", "Transition"]


def __getattr__(name: str) -> Any:
    """Keep AgentWorker import-compatible without creating repository cycles."""
    if name == "AgentWorker":
        from .agent import AgentWorker

        return AgentWorker
    raise AttributeError(name)
