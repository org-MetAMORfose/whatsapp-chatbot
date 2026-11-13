"""The immediate care nodes published by migration 0019, read back from PostgreSQL (FLOW_TEST_DATABASE_URL)."""
import os
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.chat_flow import ChatFlow, Node, Transition
from app.domain.enum.chatbot_flow import InputType, NodeType
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.services.chatbot_flow_validation_service import ChatFlowValidator

KEYS = (
    "paciente_imediato",
    "imediato_triagem_2",
    "imediato_emergencia",
    "imediato_termos",
    "imediato_recusa",
    "imediato_duracao",
    "imediato_pix",
    "imediato_na_fila",
    "imediato_em_andamento",
    "imediato_cancelado",
    "imediato_encerrado",
)


def database_url() -> str:
    value = os.getenv("FLOW_TEST_DATABASE_URL")
    if not value:
        pytest.skip("FLOW_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


def node(flow: ChatFlow, key: str) -> Node:
    found = flow.get(key)
    assert found is not None, key
    return found


def targets(found: Node) -> dict[str | None, str]:
    return {transition.expected_value: transition.target for transition in found.transitions}


def action_keys(transition: Transition) -> list[str]:
    return [action.action_key for action in transition.actions]


def config_of(transition: Transition) -> dict[str, Any]:
    config = transition.actions[0].config
    assert config is not None
    return config


def route_of(transition: Transition) -> tuple[str, str]:
    config = config_of(transition)
    assert config["config_type"] == "action_transition" and config["operator"] == "eq" and config["value"] is True
    return str(config["source"]["field"]), str(config["target_node_key"])


@pytest.mark.integration
def test_immediate_nodes_are_published_and_loadable() -> None:
    engine = create_engine(database_url())
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        _version, flow = ChatFlowRepository(factory).load()
        validation = ChatFlowValidator().validate(flow)
        assert validation.valid, validation.model_dump()
        for key in KEYS:
            node(flow, key)

        triage = node(flow, "paciente_imediato")
        assert triage.type == NodeType.MESSAGE
        assert triage.message.startswith("Antes de continuar, duas perguntas rápidas.")
        assert triage.buttons == ["Não", "Sim"]
        assert targets(triage) == {"Não": "imediato_triagem_2", "Sim": "imediato_emergencia"}
        assert targets(node(flow, "imediato_triagem_2")) == {"Não": "imediato_termos", "Sim": "imediato_emergencia"}

        emergency = node(flow, "imediato_emergencia")
        assert emergency.type == NodeType.END
        assert "188" in emergency.message and "192" in emergency.message

        terms = node(flow, "imediato_termos")
        assert terms.buttons == ["Aceito os termos", "Não aceito"]
        assert targets(terms) == {"Aceito os termos": "imediato_duracao", "Não aceito": "imediato_recusa"}
        assert node(flow, "imediato_recusa").type == NodeType.END

        duration = node(flow, "imediato_duracao")
        assert duration.buttons == ["30 minutos", "50 minutos"]
        for transition in duration.transitions:
            assert transition.target == "imediato_pix"
            assert action_keys(transition) == ["immediate_create_request"]
            assert transition.actions[0].is_required is True
            assert route_of(transition) == ("immediate_active", "imediato_em_andamento")
        assert node(flow, "imediato_em_andamento").type == NodeType.END

        pix = node(flow, "imediato_pix")
        assert pix.type == NodeType.MESSAGE
        assert [transition.expected_value for transition in pix.transitions] == ["cancelar", None]
        cancel, waiting = pix.transitions
        assert cancel.input_type == InputType.TEXT and cancel.button_label is None
        assert cancel.target == "imediato_cancelado" and action_keys(cancel) == ["immediate_cancel"]
        assert cancel.actions[0].is_required is True
        assert waiting.input_type == InputType.AUTO and waiting.target == "imediato_pix"
        assert action_keys(waiting) == ["immediate_payment_status"] and waiting.actions[0].is_required is False
        assert route_of(waiting) == ("immediate_paid", "imediato_na_fila")
        assert node(flow, "imediato_cancelado").type == NodeType.END

        queue = node(flow, "imediato_na_fila")
        assert queue.type == NodeType.MESSAGE and len(queue.transitions) == 1
        assert queue.transitions[0].input_type == InputType.AUTO and queue.transitions[0].target == "imediato_na_fila"
        assert action_keys(queue.transitions[0]) == ["immediate_payment_status"]
        assert route_of(queue.transitions[0]) == ("immediate_done", "imediato_encerrado")
        assert node(flow, "imediato_encerrado").type == NodeType.END

        assert targets(node(flow, "paciente_tipo_atendimento"))["atendimento imediato"] == "paciente_imediato"
    finally:
        engine.dispose()
