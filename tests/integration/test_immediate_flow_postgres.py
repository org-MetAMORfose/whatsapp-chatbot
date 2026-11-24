"""The immediate care nodes published by migration 0019, read back from PostgreSQL (FLOW_TEST_DATABASE_URL)."""

import os
import subprocess
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.agent import normalize_text
from app.agent.chat_flow import ChatFlow, Node, Transition
from app.domain.enum.chatbot_flow import InputType, NodeType
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.services.chatbot_flow_validation_service import ChatFlowValidator

KEYS = (
    "paciente_imediato",
    "imediato_triagem_2",
    "imediato_emergencia",
    "imediato_idade",
    "imediato_menor",
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
    "imediato_area",
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


def assert_offers_scheduling(flow: ChatFlow, key: str) -> Node:
    """Giving up on the immediate care ends in one button that continues on the chosen area's scheduling path."""
    found = node(flow, key)
    scheduling = node(flow, "paciente_inicio")
    assert found.type == NodeType.MESSAGE and found.buttons == ["Agendar atendimento"]
    assert found.message.endswith("Se preferir, posso te ajudar a agendar um atendimento nessa área.")
    (button,) = found.transitions
    assert button.target == "paciente_inicio"  # an unknown area asks for it again
    routes = {
        str(action.config["value"]): str(action.config["target_node_key"])
        for action in button.actions
        if action.config is not None and action.config["source"]["field"] == "immediate_area"
    }
    assert routes == {normalize_text(option.expected_value or ""): option.target for option in scheduling.transitions}
    assert "immediate_area_route" in action_keys(button)
    assert all(action.is_required is False for action in button.actions if action.action_key.startswith("immediate_"))
    return found


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
        assert triage.message.startswith("Antes de continuar, algumas perguntas rápidas.")
        assert triage.buttons == ["Não", "Sim"]
        assert targets(triage) == {"Não": "imediato_triagem_2", "Sim": "imediato_emergencia"}
        assert targets(node(flow, "imediato_triagem_2")) == {"Não": "imediato_idade", "Sim": "imediato_emergencia"}
        age = node(flow, "imediato_idade")
        assert age.message == "Você tem 18 anos ou mais?" and targets(age) == {"Sim": "imediato_termos", "Não": "imediato_menor"}
        minor = node(flow, "imediato_menor")
        assert minor.type == NodeType.END and "18 anos" in minor.message and "188" in minor.message

        emergency = node(flow, "imediato_emergencia")
        assert emergency.type == NodeType.END
        assert "188" in emergency.message and "192" in emergency.message

        terms = node(flow, "imediato_termos")
        assert terms.buttons == ["Aceito os termos", "Não aceito"]
        assert targets(terms) == {"Aceito os termos": "imediato_duracao", "Não aceito": "imediato_recusa"}
        accept_terms = next(transition for transition in terms.transitions if transition.expected_value == "Aceito os termos")
        assert action_keys(accept_terms) == ["immediate_prices"] and accept_terms.actions[0].is_required is False
        assert "uma sessão única por vídeo com profissional de saúde da Rede" in terms.message
        assert_offers_scheduling(flow, "imediato_recusa")

        duration = node(flow, "imediato_duracao")
        assert duration.buttons == ["10 minutos", "20 minutos", "40 minutos", "60 minutos"]
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
        nobody = assert_offers_scheduling(flow, "imediato_sem_profissional")
        assert nobody.message.startswith("Nenhum profissional dessa área está disponível")
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
        assert_offers_scheduling(flow, "imediato_cancelado")
        assert "psicólogo" not in pix.message

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
        assert "psicólogo" not in queue.message and queue.title == "Procurando um profissional"

        # The area comes first, right after "Atendimento imediato": the same options the scheduling flow offers.
        menu = node(flow, "paciente_tipo_atendimento")
        assert targets(menu)["atendimento imediato"] == "imediato_area"
        area_question = node(flow, "imediato_area")
        scheduling = node(flow, "paciente_inicio")
        assert area_question.type == NodeType.MESSAGE and area_question.message == "Em qual área você quer ser atendido?"
        assert area_question.buttons == scheduling.buttons and len(area_question.buttons or []) >= 2
        for transition in area_question.transitions:
            assert transition.target == "paciente_imediato"
            assert action_keys(transition) == ["redis_update_patient_area"]
        entry = next(transition for transition in menu.transitions if transition.expected_value == "atendimento imediato")
        assert action_keys(entry) == ["postgres_route_patient_registration", "immediate_gate"]
        gate = entry.actions[1]
        assert gate.is_required is True and gate.config is not None
        assert gate.config["source"]["field"] == "immediate_disabled" and gate.config["target_node_key"] == "imediato_indisponivel"
        assert node(flow, "imediato_indisponivel").type == NodeType.END
    finally:
        engine.dispose()


def _scratch_database(name: str) -> str:
    """A throwaway database migrated up to 0018, so 0019 can be run against an edited flow."""
    from sqlalchemy.engine import make_url

    url = make_url(database_url())
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    scratch = url.set(database=name).render_as_string(hide_password=False)
    engine = create_engine(scratch)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    engine.dispose()
    _alembic(scratch, "upgrade", "0018_immediate_care")
    return scratch


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": url, "PYTHON_DOTENV_DISABLED": "1"}
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", *args], env=env, capture_output=True, text=True, check=False
    )


def _drop(name: str) -> None:
    from sqlalchemy.engine import make_url

    admin = create_engine(make_url(database_url()).set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.mark.integration
def test_0019_stops_without_writing_when_the_production_flow_was_edited() -> None:
    """The team edited the placeholder in the panel: the migration refuses, explains why and leaves 0018 + flow untouched."""
    name = "immediate_0019_edited"
    scratch = _scratch_database(name)
    try:
        engine = create_engine(scratch)
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE chatbot_flow.node SET message = 'Peça pelo link https://exemplo.com/imediato' WHERE key = 'paciente_imediato'")
            )
        result = _alembic(scratch, "upgrade", "head")
        assert result.returncode != 0
        assert "Migração 0019 (acolhimento imediato) não aplicada" in result.stderr
        assert "o nó 'paciente_imediato' foi editado" in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0018_immediate_care"
            assert connection.scalar(sa.text("SELECT message FROM chatbot_flow.node WHERE key = 'paciente_imediato'")) == (
                "Peça pelo link https://exemplo.com/imediato"
            )
            assert connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.node WHERE key LIKE 'imediato%'")) == 0
            assert connection.scalar(sa.text("SELECT max(version) FROM chatbot_flow.graph_revision")) == 1
        engine.dispose()
    finally:
        _drop(name)


@pytest.mark.integration
def test_0019_accepts_the_placeholder_text_the_team_published_in_production() -> None:
    """Production (revision 14, 06/11/2026) swapped the link text for a question but kept the node a dead end."""
    name = "immediate_0019_production_text"
    scratch = _scratch_database(name)
    try:
        engine = create_engine(scratch)
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE chatbot_flow.node SET message = :message WHERE key = 'paciente_imediato'"),
                {"message": "Qual área você quer atendimento imediato? Vamos te conectar o mais rápido possível com um profissional de saúde"},
            )
        result = _alembic(scratch, "upgrade", "0019_immediate_flow")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0019_immediate_flow"
            assert connection.scalar(sa.text("SELECT CAST(type AS text) FROM chatbot_flow.node WHERE key = 'paciente_imediato'")) == "MESSAGE"
            assert "Você está pensando em se machucar" in connection.scalar(
                sa.text("SELECT message FROM chatbot_flow.node WHERE key = 'paciente_imediato'")
            )
        engine.dispose()
    finally:
        _drop(name)


@pytest.mark.integration
def test_0019_publishes_a_revision_that_marks_open_drafts_as_stale() -> None:
    from app.services.chatbot_flow_admin_service import ChatFlowAdminService

    name = "immediate_0019_drafts"
    scratch = _scratch_database(name)
    try:
        engine = create_engine(scratch)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        service = ChatFlowAdminService(factory, AsyncMock())
        published = service.list_revisions()["published"]
        draft = service.create_draft(published["id"])
        assert _alembic(scratch, "upgrade", "0019_immediate_flow").returncode == 0
        revisions = service.list_revisions()
        assert revisions["published"]["version"] == 2
        assert [item["is_stale"] for item in revisions["drafts"] if item["id"] == draft["id"]] == [True]
        assert _alembic(scratch, "downgrade", "0018_immediate_care").returncode == 0
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT max(version) FROM chatbot_flow.graph_revision WHERE status = 'PUBLISHED'")) == 3
            assert connection.scalar(sa.text("SELECT CAST(type AS text) FROM chatbot_flow.node WHERE key = 'paciente_imediato'")) == "END"
        engine.dispose()
    finally:
        _drop(name)


@pytest.mark.integration
def test_0020_stops_without_writing_when_the_entry_no_longer_leads_to_the_triage() -> None:
    name = "immediate_0020_edited"
    scratch = _scratch_database(name)
    try:
        assert _alembic(scratch, "upgrade", "0019_immediate_flow").returncode == 0
        engine = create_engine(scratch)
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE chatbot_flow.transition SET next_node_id = (SELECT id FROM chatbot_flow.node WHERE key = 'imediato_termos') "
                    "WHERE lower(expected_value) = 'atendimento imediato'"
                )
            )
        result = _alembic(scratch, "upgrade", "head")
        assert result.returncode != 0
        assert "Migração 0020 (acolhimento imediato para todas as áreas) não aplicada" in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "0019_immediate_flow"
            assert connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.node WHERE key = 'imediato_area'")) == 0
            assert connection.scalar(sa.text("SELECT max(version) FROM chatbot_flow.graph_revision")) == 2
        engine.dispose()
    finally:
        _drop(name)


@pytest.mark.integration
def test_0020_keeps_texts_the_team_rewrote_and_downgrade_restores_the_previous_flow() -> None:
    name = "immediate_0020_round_trip"
    scratch = _scratch_database(name)
    try:
        assert _alembic(scratch, "upgrade", "0019_immediate_flow").returncode == 0
        engine = create_engine(scratch)
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE chatbot_flow.node SET message = 'Texto da equipe.' WHERE key = 'imediato_recusa'"))
        assert _alembic(scratch, "upgrade", "head").returncode == 0
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT message FROM chatbot_flow.node WHERE key = 'imediato_recusa'")) == (
                "Texto da equipe.\n\nSe preferir, posso te ajudar a agendar um atendimento nessa área."
            )
            columns = [
                row[0]
                for row in connection.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'immediate_request'"))
            ]
            assert "area" in columns
        result = _alembic(scratch, "downgrade", "0019_immediate_flow")
        assert result.returncode == 0, result.stderr
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.node WHERE key = 'imediato_area'")) == 0
            assert connection.scalar(sa.text("SELECT CAST(type AS text) FROM chatbot_flow.node WHERE key = 'imediato_recusa'")) == "END"
            assert connection.scalar(sa.text("SELECT message FROM chatbot_flow.node WHERE key = 'imediato_recusa'")) == "Texto da equipe."
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT node.key FROM chatbot_flow.transition AS transition "
                        "JOIN chatbot_flow.node AS node ON node.id = transition.next_node_id "
                        "WHERE lower(transition.expected_value) = 'atendimento imediato'"
                    )
                )
                == "paciente_imediato"
            )
            assert connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.transition_action WHERE action_key = 'immediate_area_route'")) == 0
            assert "com um psicólogo da Rede" in connection.scalar(sa.text("SELECT message FROM chatbot_flow.node WHERE key = 'imediato_termos'"))
        engine.dispose()
    finally:
        _drop(name)
