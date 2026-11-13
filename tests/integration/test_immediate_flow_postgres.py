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
    "imediato_indisponivel",
    "imediato_sem_profissional",
    "imediato_falha_pix",
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


def routes_of(transition: Transition) -> dict[str, str]:
    """Every action_transition config on the transition, field -> target."""
    routes: dict[str, str] = {}
    for action in transition.actions:
        if action.config is not None:
            assert action.config["operator"] == "eq" and action.config["value"] is True
            routes[str(action.config["source"]["field"])] = str(action.config["target_node_key"])
    return routes


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
            assert action_keys(transition) == ["immediate_create_request", "immediate_noop", "immediate_noop", "immediate_noop"]
            assert [action.is_required for action in transition.actions] == [True, False, False, False]
            assert routes_of(transition) == {
                "immediate_active": "imediato_em_andamento",
                "immediate_nobody_available": "imediato_sem_profissional",
                "immediate_disabled": "imediato_indisponivel",
                "immediate_pix_failed": "imediato_falha_pix",
            }
        assert node(flow, "imediato_em_andamento").type == NodeType.END
        assert node(flow, "imediato_sem_profissional").type == NodeType.END
        failure = node(flow, "imediato_falha_pix")
        assert failure.type == NodeType.END and failure.message.startswith("Não consegui gerar o Pix agora.")

        pix = node(flow, "imediato_pix")
        assert pix.type == NodeType.MESSAGE
        assert [transition.expected_value for transition in pix.transitions] == ["cancelar", None]
        cancel, waiting = pix.transitions
        assert cancel.input_type == InputType.TEXT and cancel.button_label is None
        assert cancel.target == "imediato_cancelado" and action_keys(cancel) == ["immediate_cancel", "immediate_noop"]
        assert [action.is_required for action in cancel.actions] == [True, False]
        assert routes_of(cancel) == {"immediate_paid": "imediato_na_fila", "immediate_done": "imediato_encerrado"}
        assert waiting.input_type == InputType.AUTO and waiting.target == "imediato_pix"
        assert action_keys(waiting) == ["immediate_payment_status", "immediate_noop"]
        assert [action.is_required for action in waiting.actions] == [False, False]
        assert routes_of(waiting) == {"immediate_paid": "imediato_na_fila", "immediate_done": "imediato_encerrado"}
        assert node(flow, "imediato_cancelado").type == NodeType.END

        queue = node(flow, "imediato_na_fila")
        assert queue.type == NodeType.MESSAGE
        assert [transition.expected_value for transition in queue.transitions] == ["cancelar", None]
        queue_cancel, queue_waiting = queue.transitions
        assert queue_cancel.input_type == InputType.TEXT and queue_cancel.target == "imediato_na_fila"
        assert action_keys(queue_cancel) == ["immediate_cancel", "immediate_noop"]
        assert routes_of(queue_cancel) == {"immediate_paid": "imediato_na_fila", "immediate_done": "imediato_encerrado"}
        assert queue_waiting.input_type == InputType.AUTO and queue_waiting.target == "imediato_na_fila"
        assert action_keys(queue_waiting) == ["immediate_payment_status"]
        assert route_of(queue_waiting) == ("immediate_done", "imediato_encerrado")
        assert node(flow, "imediato_encerrado").type == NodeType.END

        menu = node(flow, "paciente_tipo_atendimento")
        assert targets(menu)["atendimento imediato"] == "paciente_imediato"
        entry = next(transition for transition in menu.transitions if transition.expected_value == "atendimento imediato")
        assert action_keys(entry) == ["postgres_route_patient_registration", "immediate_gate"]
        gate = entry.actions[1]
        assert gate.is_required is True and gate.config is not None
        assert gate.config["source"]["field"] == "immediate_disabled" and gate.config["target_node_key"] == "imediato_indisponivel"
        assert node(flow, "imediato_indisponivel").type == NodeType.END
    finally:
        engine.dispose()
