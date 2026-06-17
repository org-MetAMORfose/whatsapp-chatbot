import pytest

from app.agent.chat_flow import ChatFlow


def test_from_data_requires_start_node() -> None:
    data = {
        "nodes": {
            "only_node": {
                "message": "Mensagem qualquer",
                "end": True,
            }
        }
    }

    with pytest.raises(ValueError, match="start"):
        ChatFlow.from_data(data)


def test_from_data_accepts_flow_with_start_node() -> None:
    data = {
        "nodes": {
            "start": {
                "message": "Inicio",
                "transitions": [
                    {
                        "target": "end",
                        "conditions": [],
                    }
                ],
            },
            "end": {
                "message": "Fim",
                "end": True,
            },
        }
    }

    flow = ChatFlow.from_data(data)

    assert "start" in flow.nodes


def test_active_flow_contains_start_node() -> None:
    flow = ChatFlow.from_file()

    assert "start" in flow.nodes


def test_active_flow_transitions_target_existing_nodes() -> None:
    flow = ChatFlow.from_file()

    missing_targets = [
        (node_id, transition.target)
        for node_id, node in flow.nodes.items()
        for transition in node.transitions
        if transition.target not in flow.nodes
    ]

    assert missing_targets == []
