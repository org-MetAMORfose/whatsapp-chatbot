"""Immediate care for every area: the patient picks the area first, and giving up leads to scheduling in it.

- `immediate_request.area`: the chosen area; offers go only to released professionals of that area.
- New node `imediato_area`, right after "Atendimento imediato", with the same options as the scheduling
  question (`paciente_inicio`), read from the live flow. It stores the area exactly as scheduling does.
- `imediato_recusa`, `imediato_cancelado` and `imediato_sem_profissional` stop being dead ends: one button,
  "Agendar atendimento", continues on the scheduling path of the area already chosen.
- Copy no longer says "psicólogo".

As in 0019, the flow is data the team edits in the panel: every precondition is checked before anything is
written, and both directions publish a new graph revision.
"""

import json
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "0020_immediate_all_areas"
down_revision = "0019_immediate_flow"
branch_labels = None
depends_on = None

AREA_NODE = "imediato_area"
AREA_MESSAGE = "Em qual área você quer ser atendido?"
SCHEDULING_NODE = "paciente_inicio"
TRIAGE_NODE = "paciente_imediato"
ENTRY_NODE, ENTRY_VALUE = "paciente_tipo_atendimento", "atendimento imediato"
SCHEDULE_ENTRY_VALUE = "agendar atendimento"
SCHEDULE_BUTTON = "Agendar atendimento"
SCHEDULE_OFFER = "Se preferir, posso te ajudar a agendar um atendimento nessa área."

# key -> (text written by 0019, text that replaces it). A text the team rewrote is kept, with the offer appended.
EXITS: dict[str, tuple[str, str]] = {
    "imediato_recusa": ("Tudo bem. Se mudar de ideia, mande RESET e recomece.", f"Tudo bem. {SCHEDULE_OFFER}"),
    "imediato_cancelado": (
        "Pedido cancelado. Nada foi cobrado. Se precisar, mande RESET e recomece.",
        f"Pedido cancelado. Nada foi cobrado. {SCHEDULE_OFFER}",
    ),
    "imediato_sem_profissional": (
        "Nenhum psicólogo está disponível para atendimento imediato agora, então não vou gerar a cobrança. "
        "Tente de novo mais tarde ou mande RESET e escolha Agendar atendimento.",
        f"Nenhum profissional dessa área está disponível para atendimento imediato agora, então não vou gerar a cobrança. {SCHEDULE_OFFER}",
    ),
}

# (node key, column, old fragment, new fragment): replaced in place, so the rest of an edited text survives.
WORDING: tuple[tuple[str, str, str, str], ...] = (
    ("imediato_termos", "message", "com um psicólogo da Rede", "com profissional de saúde da Rede"),
    ("imediato_pix", "message", "um psicólogo disponível", "um profissional disponível"),
    ("imediato_na_fila", "message", "um psicólogo disponível", "um profissional disponível"),
    ("imediato_na_fila", "title", "Procurando um psicólogo", "Procurando um profissional"),
    ("imediato_sem_profissional", "title", "Nenhum psicólogo disponível", "Nenhum profissional disponível"),
)


def _normalized(value: str) -> str:
    """Same normalization as app.domain.matching.profile.key: no accents, case or extra spaces."""
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    return " ".join("".join(character for character in decomposed if not unicodedata.combining(character)).split())


def _area_route(area_key: str, target: str) -> dict[str, object]:
    return {
        "config_type": "action_transition",
        "source": {"type": "action_result", "field": "immediate_area"},
        "operator": "eq",
        "value": area_key,
        "target_node_key": target,
    }


def _node(connection: Connection, key: str) -> tuple[int, str] | None:
    row = connection.execute(sa.text("SELECT id, CAST(type AS text) FROM chatbot_flow.node WHERE key = :key"), {"key": key}).first()
    return None if row is None else (int(row[0]), str(row[1]))


def _outgoing(connection: Connection, node_id: int) -> int:
    return int(connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.transition WHERE node_id = :node_id"), {"node_id": node_id}) or 0)


def _entry_transition(connection: Connection, expected: str) -> tuple[int, int | None] | None:
    row = connection.execute(
        sa.text(
            "SELECT transition.id, transition.next_node_id FROM chatbot_flow.transition AS transition "
            "JOIN chatbot_flow.node AS node ON node.id = transition.node_id "
            "WHERE node.key = :node_key AND lower(transition.expected_value) = :expected"
        ),
        {"node_key": ENTRY_NODE, "expected": expected},
    ).first()
    return None if row is None else (int(row[0]), None if row[1] is None else int(row[1]))


def _area_options(connection: Connection) -> list[tuple[str, str | None, str, int]]:
    """(expected_value, button_label, target key, position) of every area the scheduling question offers."""
    rows = connection.execute(
        sa.text(
            "SELECT transition.expected_value, transition.button_label, target.key, transition.position "
            "FROM chatbot_flow.transition AS transition "
            "JOIN chatbot_flow.node AS node ON node.id = transition.node_id "
            "JOIN chatbot_flow.node AS target ON target.id = transition.next_node_id "
            "WHERE node.key = :key AND CAST(transition.input_type AS text) = 'TEXT' AND transition.expected_value IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM chatbot_flow.transition_action AS action "
            "WHERE action.transition_id = transition.id AND action.action_key = 'redis_update_patient_area') "
            "ORDER BY transition.position, transition.id"
        ),
        {"key": SCHEDULING_NODE},
    )
    return [(str(expected), None if button is None else str(button), str(target), int(position)) for expected, button, target, position in rows]


def _upgrade_problems(connection: Connection) -> list[str]:
    """Everything the upgrade relies on, read before any write."""
    problems: list[str] = []
    triage = _node(connection, TRIAGE_NODE)
    if triage is None:
        problems.append(f"o nó '{TRIAGE_NODE}' não existe")
    if _node(connection, AREA_NODE) is not None:
        problems.append(f"já existe um nó '{AREA_NODE}'")
    entry = _entry_transition(connection, ENTRY_VALUE)
    if entry is None:
        problems.append(f"o botão 'Atendimento imediato' do nó '{ENTRY_NODE}' não existe mais")
    elif triage is not None and entry[1] != triage[0]:
        problems.append(f"o botão 'Atendimento imediato' não leva mais ao nó '{TRIAGE_NODE}'")
    if _node(connection, SCHEDULING_NODE) is None:
        problems.append(f"o nó '{SCHEDULING_NODE}' (pergunta de área do agendamento) não existe")
    elif not _area_options(connection):
        problems.append(f"o nó '{SCHEDULING_NODE}' não tem mais opções de área com a ação redis_update_patient_area")
    for key in EXITS:
        found = _node(connection, key)
        if found is None:
            problems.append(f"o nó '{key}' não existe")
        elif found[1] != "END" or _outgoing(connection, found[0]):
            problems.append(f"o nó '{key}' não é mais um fim sem saídas")
    if connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.graph_revision WHERE status = 'PUBLISHED'")) == 0:
        problems.append("não há revisão publicada do fluxo")
    return problems


def _insert_transition(connection: Connection, node_id: int, expected: str, button: str | None, target_id: int, position: int) -> int:
    return int(
        connection.execute(
            sa.text(
                "INSERT INTO chatbot_flow.transition (node_id, input_type, expected_value, button_label, next_node_id, position) "
                "VALUES (:node_id, CAST('TEXT' AS chatbot_flow.input_type), :expected, :button, :target_id, :position) RETURNING id"
            ),
            {"node_id": node_id, "expected": expected, "button": button, "target_id": target_id, "position": position},
        ).scalar_one()
    )


def _insert_action(connection: Connection, transition_id: int, action_key: str, config: object, is_required: bool) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO chatbot_flow.transition_action (transition_id, action_key, config, is_required) "
            "VALUES (:transition_id, :action_key, CAST(:config AS jsonb), :is_required)"
        ),
        {
            "transition_id": transition_id,
            "action_key": action_key,
            "config": json.dumps(config) if config is not None else None,
            "is_required": is_required,
        },
    )


def _publish_revision(connection: Connection) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO chatbot_flow.graph_revision (base_revision_id, status, version, created_at, updated_at, published_at) "
            "SELECT id, CAST('PUBLISHED' AS chatbot_flow.revision_status), version + 1, now(), now(), now() FROM chatbot_flow.graph_revision "
            "WHERE status = 'PUBLISHED' ORDER BY version DESC LIMIT 1"
        )
    )


def _replace(connection: Connection, key: str, column: str, old: str, new: str) -> None:
    if column not in ("message", "title"):
        raise ValueError(column)
    connection.execute(
        sa.text(f"UPDATE chatbot_flow.node SET {column} = replace({column}, :old, :new) WHERE key = :key"),  # noqa: S608
        {"key": key, "old": old, "new": new},
    )


def upgrade() -> None:
    connection = op.get_bind()
    problems = _upgrade_problems(connection)
    if problems:
        raise RuntimeError(
            "Migração 0020 (acolhimento imediato para todas as áreas) não aplicada: o fluxo de produção é diferente do esperado. "
            "Nada foi alterado e o bot continua com a versão anterior. Diferenças: " + "; ".join(problems) + ". "
            "Desfaça essas mudanças no editor do fluxo (ou ajuste a migração) e rode o deploy de novo."
        )
    op.add_column("immediate_request", sa.Column("area", sa.String()))

    options = _area_options(connection)
    triage = _node(connection, TRIAGE_NODE)
    scheduling = _node(connection, SCHEDULING_NODE)
    entry = _entry_transition(connection, ENTRY_VALUE)
    if triage is None or scheduling is None or entry is None:  # already reported by _upgrade_problems
        raise RuntimeError("Immediate care flow nodes not found")

    # 1. The area question, between the menu and the triage.
    position = int(connection.scalar(sa.text("SELECT COALESCE(MAX(position), 0) FROM chatbot_flow.node")) or 0)
    area_id = int(
        connection.execute(
            sa.text(
                "INSERT INTO chatbot_flow.node (key, type, title, description, message, position, position_x, position_y) "
                "VALUES (:key, CAST('MESSAGE' AS chatbot_flow.node_type), :title, :description, :message, :position, 2900, 200) RETURNING id"
            ),
            {
                "key": AREA_NODE,
                "title": "Área do atendimento imediato",
                "description": "Primeira pergunta do imediato; a área vale também para o agendamento se o paciente desistir.",
                "message": AREA_MESSAGE,
                "position": position + 1,
            },
        ).scalar_one()
    )
    for expected, button, _target, option_position in options:
        transition_id = _insert_transition(connection, area_id, expected, button, triage[0], option_position)
        _insert_action(connection, transition_id, "redis_update_patient_area", None, False)
    connection.execute(sa.text("UPDATE chatbot_flow.transition SET next_node_id = :area WHERE id = :id"), {"area": area_id, "id": entry[0]})

    # 2. Giving up ends in "Agendar atendimento", on the scheduling path of the area already chosen.
    schedule_entry = _entry_transition(connection, SCHEDULE_ENTRY_VALUE)
    returning_actions = (
        []
        if schedule_entry is None
        else connection.execute(
            sa.text(
                "SELECT action_key, config, is_required FROM chatbot_flow.transition_action "
                "WHERE transition_id = :id AND config IS NOT NULL ORDER BY id"
            ),
            {"id": schedule_entry[0]},
        ).all()
    )
    for key, (seeded, replacement) in EXITS.items():
        exit_node = _node(connection, key)
        if exit_node is None:
            raise RuntimeError(f"Node {key} not found")
        connection.execute(
            sa.text(
                "UPDATE chatbot_flow.node SET type = CAST('MESSAGE' AS chatbot_flow.node_type), "
                "message = CASE WHEN message = :seeded THEN :replacement ELSE message || :appended END WHERE id = :id"
            ),
            {"seeded": seeded, "replacement": replacement, "appended": f"\n\n{SCHEDULE_OFFER}", "id": exit_node[0]},
        )
        transition_id = _insert_transition(connection, exit_node[0], SCHEDULE_BUTTON, SCHEDULE_BUTTON, scheduling[0], 0)
        # A returning patient goes to their summary, exactly as from the menu's "Agendar atendimento".
        for action_key, config, is_required in returning_actions:
            _insert_action(connection, transition_id, str(action_key), config, bool(is_required))
        for index, (expected, _button, target, _position) in enumerate(options):
            _insert_action(
                connection,
                transition_id,
                "immediate_area_route" if index == 0 else "immediate_noop",
                _area_route(_normalized(expected), target),
                False,
            )

    # 3. Wording: any area, not only psychologists.
    for key, column, old, new in WORDING:
        _replace(connection, key, column, old, new)
    _publish_revision(connection)


def downgrade() -> None:
    connection = op.get_bind()
    for key, column, old, new in WORDING:
        _replace(connection, key, column, new, old)
    for key, (seeded, replacement) in EXITS.items():
        exit_node = _node(connection, key)
        if exit_node is None:
            continue
        connection.execute(
            sa.text(
                "DELETE FROM chatbot_flow.transition_action WHERE transition_id IN "
                "(SELECT id FROM chatbot_flow.transition WHERE node_id = :id AND expected_value = :button)"
            ),
            {"id": exit_node[0], "button": SCHEDULE_BUTTON},
        )
        connection.execute(
            sa.text("DELETE FROM chatbot_flow.transition WHERE node_id = :id AND expected_value = :button"),
            {"id": exit_node[0], "button": SCHEDULE_BUTTON},
        )
        appended = f"\n\n{SCHEDULE_OFFER}"
        connection.execute(
            sa.text(
                "UPDATE chatbot_flow.node SET type = CAST('END' AS chatbot_flow.node_type), message = CASE "
                "WHEN message = :replacement THEN :seeded "
                "WHEN right(message, :length) = :appended THEN left(message, char_length(message) - :length) "
                "ELSE message END WHERE id = :id"
            ),
            {"replacement": replacement, "seeded": seeded, "appended": appended, "length": len(appended), "id": exit_node[0]},
        )
    area_node = _node(connection, AREA_NODE)
    triage = _node(connection, TRIAGE_NODE)
    if area_node is not None:
        if triage is not None:
            connection.execute(
                sa.text("UPDATE chatbot_flow.transition SET next_node_id = :triage WHERE next_node_id = :area"),
                {"triage": triage[0], "area": area_node[0]},
            )
        connection.execute(
            sa.text("DELETE FROM chatbot_flow.transition_action WHERE transition_id IN (SELECT id FROM chatbot_flow.transition WHERE node_id = :id)"),
            {"id": area_node[0]},
        )
        connection.execute(sa.text("DELETE FROM chatbot_flow.transition WHERE node_id = :id"), {"id": area_node[0]})
        connection.execute(sa.text("DELETE FROM chatbot_flow.node WHERE id = :id"), {"id": area_node[0]})
    op.drop_column("immediate_request", "area")
    _publish_revision(connection)
