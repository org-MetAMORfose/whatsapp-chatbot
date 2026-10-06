from app.agent.chat_flow import ChatFlow, Node, Transition, TransitionAction
from app.domain.enum.chatbot_flow import InputType, NodeType
from app.services.chatbot_flow_validation_service import ChatFlowValidator


def node(
    node_id: int,
    key: str,
    node_type: NodeType,
    *,
    transitions: list[Transition] | None = None,
) -> Node:
    return Node(
        id=node_id,
        key=key,
        type=node_type,
        title=key,
        message=key,
        position=node_id,
        transitions=transitions or [],
    )


def transition(
    transition_id: int,
    target: str,
    *,
    actions: list[TransitionAction] | None = None,
    button_label: str | None = None,
) -> Transition:
    return Transition(
        id=transition_id,
        input_type=InputType.AUTO,
        target=target,
        position=0,
        button_label=button_label,
        actions=actions or [],
    )


def validate(*nodes: Node):
    flow = ChatFlow.model_construct(
        nodes={item.key: item for item in nodes},
        input_error_messages={},
    )
    return ChatFlowValidator().validate(flow)


def codes(*nodes: Node) -> set[str]:
    return {error.code for error in validate(*nodes).errors}


def test_validates_reachability_in_both_directions() -> None:
    result = codes(
        node(1, "start", NodeType.START, transitions=[transition(1, "end")]),
        node(2, "orphan", NodeType.MESSAGE),
        node(3, "end", NodeType.END),
    )

    assert "NODE_CANNOT_REACH_END" in result
    assert "NODE_NOT_REACHABLE_FROM_START" in result


def test_rejects_transitions_leaving_an_end_node() -> None:
    result = codes(
        node(1, "start", NodeType.START, transitions=[transition(1, "end")]),
        node(2, "end", NodeType.END, transitions=[transition(2, "end")]),
    )

    assert "END_HAS_TRANSITIONS" in result


def test_action_config_transition_counts_as_a_graph_edge() -> None:
    action = TransitionAction(
        id=10,
        action_key="route",
        config={
            "config_type": "action_transition",
            "source": {"type": "action_result", "field": "route"},
            "operator": "eq",
            "value": "support",
            "target_node_key": "support",
        },
    )
    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[action])],
        ),
        node(2, "support", NodeType.MESSAGE, transitions=[transition(2, "end")]),
        node(3, "end", NodeType.END),
    )

    assert result.valid


def test_rejects_invalid_action_config_operator_and_target() -> None:
    invalid_operator = TransitionAction(
        id=10,
        action_key="route",
        config={
            "config_type": "action_transition",
            "source": {"type": "action_result", "field": "route"},
            "operator": "contains",
            "value": "support",
            "target_node_key": "missing",
        },
    )
    invalid_target = TransitionAction(
        id=11,
        action_key="route",
        config={
            "config_type": "action_transition",
            "source": {"type": "action_result", "field": "route"},
            "operator": "eq",
            "value": "support",
            "target_node_key": "missing",
        },
    )
    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[invalid_operator, invalid_target])],
        ),
        node(2, "end", NodeType.END),
    )

    assert {error.code for error in result.errors} >= {
        "INVALID_ACTION_CONFIG",
        "INVALID_ACTION_CONFIG_TARGET",
    }


def test_rejects_circular_action_dependencies() -> None:
    first = TransitionAction(id=10, action_key="first", depends_on_ids=[11])
    second = TransitionAction(id=11, action_key="second", depends_on_ids=[10])
    result = codes(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[first, second])],
        ),
        node(2, "end", NodeType.END),
    )

    assert "CIRCULAR_ACTION_DEPENDENCY" in result


def test_dependency_must_execute_before_dependent_action() -> None:
    dependent = TransitionAction(id=11, action_key="write_postgres", depends_on_ids=[10])
    dependency = TransitionAction(id=10, action_key="read_redis")
    result = codes(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[dependent, dependency])],
        ),
        node(2, "end", NodeType.END),
    )

    assert "ACTION_DEPENDENCY_NOT_BEFORE" in result


def test_accepts_dependency_that_always_executes_first() -> None:
    dependency = TransitionAction(id=10, action_key="read_redis")
    dependent = TransitionAction(id=11, action_key="write_postgres", depends_on_ids=[10])
    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[dependency, dependent])],
        ),
        node(2, "end", NodeType.END),
    )

    assert result.valid


def test_accepts_sheets_store_before_flush_for_same_tab() -> None:
    store = TransitionAction(
        id=-1,
        action_key="sheets_store_answer",
        config={"config_type": "sheets_store_answer", "tab": "Aba 1", "column": "G"},
    )
    flush = TransitionAction(
        id=-2,
        action_key="sheets_flush",
        config={"config_type": "sheets_flush", "tab": "Aba 1"},
    )

    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "finish", actions=[store])],
        ),
        node(
            2,
            "finish",
            NodeType.MESSAGE,
            transitions=[transition(2, "end", actions=[flush])],
        ),
        node(3, "end", NodeType.END),
    )

    assert result.valid


def test_rejects_sheets_flush_without_prior_store_for_same_tab() -> None:
    store = TransitionAction(
        id=-1,
        action_key="sheets_store_answer",
        config={"config_type": "sheets_store_answer", "tab": "Outra aba", "column": "G"},
    )
    flush = TransitionAction(
        id=-2,
        action_key="sheets_flush",
        config={"config_type": "sheets_flush", "tab": "Aba 1"},
    )

    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", actions=[store, flush])],
        ),
        node(2, "end", NodeType.END),
    )

    error = next(item for item in result.errors if item.code == "SHEETS_STORE_NOT_BEFORE_FLUSH")
    assert error.action_id == -2
    assert error.details == {"tab": "Aba 1"}


def test_rejects_invalid_sheets_column() -> None:
    action = TransitionAction(
        id=-1,
        action_key="sheets_store_answer",
        config={"config_type": "sheets_store_answer", "tab": "Aba 1", "column": "g"},
    )
    result = codes(
        node(1, "start", NodeType.START, transitions=[transition(1, "end", actions=[action])]),
        node(2, "end", NodeType.END),
    )

    assert "INVALID_ACTION_CONFIG" in result


def test_rejects_button_labels_longer_than_twenty_characters() -> None:
    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", button_label="123456789012345678901")],
        ),
        node(2, "end", NodeType.END),
    )

    error = next(item for item in result.errors if item.code == "BUTTON_LABEL_TOO_LONG")
    assert error.transition_id == 1
    assert error.details == {"max_length": 20, "actual_length": 21}


def test_accepts_button_labels_with_twenty_characters() -> None:
    result = validate(
        node(
            1,
            "start",
            NodeType.START,
            transitions=[transition(1, "end", button_label="12345678901234567890")],
        ),
        node(2, "end", NodeType.END),
    )

    assert "BUTTON_LABEL_TOO_LONG" not in {error.code for error in result.errors}
