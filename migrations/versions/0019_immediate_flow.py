"""Immediate care: replace the "[URL em construção]" placeholder with the in-chat flow.

Converts `paciente_imediato` into the first triage question and adds the triage,
age, terms, duration, Pix, queue and terminal nodes. Copy lives in the database so the
panel's flow editor can adjust it. Downgrade restores the placeholder node.

The flow is data the team edits in the panel, so production may differ from the seed.
Every precondition is checked before anything is written; on a mismatch the migration
stops with the list of differences (the deploy runs migrations before stopping the bot,
so production keeps the previous version). Both directions publish a new graph revision:
the workers reload the flow and drafts opened before the deploy show up as stale.
"""

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "0019_immediate_flow"
down_revision = "0018_immediate_care"
branch_labels = None
depends_on = None

PLACEHOLDER = {
    "title": "Encaminhamento externo para atendimento imediato",
    "description": "Encaminhamento externo para atendimento imediato.",
    "message": "Você pode pedir atendimento imediato por este link:\n\n[URL em construção]",
}
# Placeholder texts the upgrade may replace: the seeded one and the one the team published in production (revision 14).
PLACEHOLDER_MESSAGES = (
    PLACEHOLDER["message"],
    "Qual área você quer atendimento imediato? Vamos te conectar o mais rápido possível com um profissional de saúde",
)

TRIAGE_1 = {
    "title": "Triagem do atendimento imediato (1 de 3)",
    "description": "Primeira pergunta de segurança antes de qualquer cobrança.",
    "message": "Antes de continuar, algumas perguntas rápidas.\n\nVocê está pensando em se machucar ou em tirar a própria vida?",
}

# (key, type, title, description, message)
NEW_NODES = (
    (
        "imediato_triagem_2",
        "MESSAGE",
        "Triagem do atendimento imediato (2 de 3)",
        "Segunda pergunta de segurança antes de qualquer cobrança.",
        "Você está passando agora por uma emergência, como uso de substâncias, violência ou uma crise intensa que precise de socorro?",
    ),
    (
        "imediato_idade",
        "MESSAGE",
        "Triagem do atendimento imediato (3 de 3)",
        "Atendimento de menores exige autorização de um responsável (CFP); o imediato é só para maiores.",
        "Você tem 18 anos ou mais?",
    ),
    (
        "imediato_menor",
        "END",
        "Menor de 18 anos",
        "O acolhimento imediato não atende menores; nunca gera cobrança.",
        "O acolhimento imediato é só para maiores de 18 anos. Para quem tem menos de 18, o atendimento precisa da autorização "
        "de um responsável legal.\n\nSe você estiver em perigo agora, ligue 188 (CVV) ou 192 (SAMU).",
    ),
    (
        "imediato_emergencia",
        "END",
        "Emergência: encaminhamento presencial",
        "Orienta serviços de emergência; nunca gera cobrança.",
        "Nesse caso, o atendimento online não é o mais seguro pra você agora. Procure ajuda imediata:\n\n"
        "• CVV: ligue 188 (24 horas, gratuito)\n• SAMU: 192\n• CAPS ou UPA mais perto de você\n\n"
        "A MetAMORfose continua aqui quando você precisar.",
    ),
    (
        "imediato_termos",
        "MESSAGE",
        "Termos do atendimento imediato",
        "Regras do serviço apresentadas antes do pagamento.",
        "Como funciona o acolhimento imediato:\n• uma sessão única por vídeo com um psicólogo da Rede;\n"
        "• o pagamento é por Pix, feito agora. Se nenhum profissional aceitar em 5 minutos, o valor volta automaticamente;\n"
        "• a sessão não é gravada.\n\nTermos completos: www.orgmetamorfose.com.br/termos",
    ),
    (
        "imediato_recusa",
        "END",
        "Termos recusados",
        "Paciente não aceitou os termos.",
        "Tudo bem. Se mudar de ideia, mande RESET e recomece.",
    ),
    (
        "imediato_duracao",
        "MESSAGE",
        "Duração do atendimento imediato",
        "Escolha da duração; a ação cria o pedido e o Pix.",
        "Quanto tempo você precisa?",
    ),
    (
        "imediato_em_andamento",
        "END",
        "Acolhimento já em andamento",
        "Paciente já tem um pedido ativo.",
        "Você já tem um acolhimento imediato em andamento. Assim que houver novidade, eu aviso por aqui.",
    ),
    (
        "imediato_pix",
        "MESSAGE",
        "Aguardando o pagamento do Pix",
        "Mostra o Pix e espera o pagamento; CANCELAR desiste.",
        "Depois que o pagamento cair, eu aviso por aqui e procuro um psicólogo disponível. Se quiser desistir antes de pagar, mande CANCELAR.",
    ),
    (
        "imediato_cancelado",
        "END",
        "Pedido cancelado",
        "Paciente desistiu antes de pagar.",
        "Pedido cancelado. Nada foi cobrado. Se precisar, mande RESET e recomece.",
    ),
    (
        "imediato_na_fila",
        "MESSAGE",
        "Procurando um psicólogo",
        "Pagamento recebido; aguardando um profissional aceitar.",
        "Estou procurando um psicólogo disponível. Te aviso aqui assim que alguém aceitar, em até 5 minutos.",
    ),
    (
        "imediato_encerrado",
        "END",
        "Acolhimento encerrado",
        "Pedido aceito, expirado ou cancelado; a conversa volta ao início.",
        "Se precisar de um novo atendimento, mande RESET e recomece.",
    ),
    (
        "imediato_indisponivel",
        "END",
        "Atendimento imediato desligado",
        "Mostrado enquanto IMMEDIATE_CARE_ENABLED estiver desligado.",
        "O atendimento imediato ainda não está disponível. Enquanto isso, você pode agendar: mande RESET e escolha Agendar atendimento.",
    ),
    (
        "imediato_sem_profissional",
        "END",
        "Nenhum psicólogo disponível",
        "Nenhum profissional disponível no momento; nenhuma cobrança é gerada.",
        "Nenhum psicólogo está disponível para atendimento imediato agora, então não vou gerar a cobrança. "
        "Tente de novo mais tarde ou mande RESET e escolha Agendar atendimento.",
    ),
    (
        "imediato_falha_pix",
        "END",
        "Falha ao gerar o Pix",
        "O banco não respondeu ao criar a cobrança; nenhum pedido fica aberto.",
        "Não consegui gerar o Pix agora. Tente de novo em alguns minutos ou mande RESET e escolha Agendar atendimento.",
    ),
)


def _route(field: str, target: str) -> dict[str, object]:
    return {
        "config_type": "action_transition",
        "source": {"type": "action_result", "field": field},
        "operator": "eq",
        "value": True,
        "target_node_key": target,
    }


CREATE_REQUEST_CONFIG = _route("immediate_active", "imediato_em_andamento")
NOBODY_CONFIG = _route("immediate_nobody_available", "imediato_sem_profissional")
PAID_CONFIG = _route("immediate_paid", "imediato_na_fila")
DONE_CONFIG = _route("immediate_done", "imediato_encerrado")
GATE_CONFIG = _route("immediate_disabled", "imediato_indisponivel")
PIX_FAILED_CONFIG = _route("immediate_pix_failed", "imediato_falha_pix")
DURATION_ACTIONS: list[tuple[str, dict[str, object] | None, bool]] = [
    ("immediate_create_request", CREATE_REQUEST_CONFIG, True),
    ("immediate_noop", NOBODY_CONFIG, False),
    ("immediate_noop", GATE_CONFIG, False),
    ("immediate_noop", PIX_FAILED_CONFIG, False),
]
CANCEL_ACTIONS: list[tuple[str, dict[str, object] | None, bool]] = [("immediate_cancel", PAID_CONFIG, True), ("immediate_noop", DONE_CONFIG, False)]
ENTRY_NODE, ENTRY_VALUE = "paciente_tipo_atendimento", "atendimento imediato"

# (node_key, input_type, expected_value, button_label, target_key, [(action_key, config, is_required)])
TRANSITIONS: tuple[tuple[str, str, str | None, str | None, str, list[tuple[str, dict[str, object] | None, bool]]], ...] = (
    ("paciente_imediato", "TEXT", "Não", "Não", "imediato_triagem_2", []),
    ("paciente_imediato", "TEXT", "Sim", "Sim", "imediato_emergencia", []),
    ("imediato_triagem_2", "TEXT", "Não", "Não", "imediato_idade", []),
    ("imediato_triagem_2", "TEXT", "Sim", "Sim", "imediato_emergencia", []),
    ("imediato_idade", "TEXT", "Sim", "Sim", "imediato_termos", []),
    ("imediato_idade", "TEXT", "Não", "Não", "imediato_menor", []),
    ("imediato_termos", "TEXT", "Aceito os termos", "Aceito os termos", "imediato_duracao", [("immediate_prices", None, False)]),
    ("imediato_termos", "TEXT", "Não aceito", "Não aceito", "imediato_recusa", []),
    ("imediato_duracao", "TEXT", "10 minutos", "10 minutos", "imediato_pix", DURATION_ACTIONS),
    ("imediato_duracao", "TEXT", "20 minutos", "20 minutos", "imediato_pix", DURATION_ACTIONS),
    ("imediato_duracao", "TEXT", "40 minutos", "40 minutos", "imediato_pix", DURATION_ACTIONS),
    ("imediato_duracao", "TEXT", "60 minutos", "60 minutos", "imediato_pix", DURATION_ACTIONS),
    ("imediato_pix", "TEXT", "cancelar", None, "imediato_cancelado", CANCEL_ACTIONS),
    ("imediato_pix", "AUTO", None, None, "imediato_pix", [("immediate_payment_status", PAID_CONFIG, False), ("immediate_noop", DONE_CONFIG, False)]),
    ("imediato_na_fila", "TEXT", "cancelar", None, "imediato_na_fila", CANCEL_ACTIONS),
    ("imediato_na_fila", "AUTO", None, None, "imediato_na_fila", [("immediate_payment_status", DONE_CONFIG, False)]),
)

NEW_KEYS = tuple(node[0] for node in NEW_NODES)


def _insert_action(connection: Connection, transition_id: int, action_key: str, config: dict[str, object] | None, is_required: bool) -> None:
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


def _node_ids(connection: Connection) -> dict[str, int]:
    """Only the nodes this migration owns: nodes the team adds later with an imediato_ prefix are left alone."""
    keys = ["paciente_imediato", *NEW_KEYS]
    rows = connection.execute(
        sa.text("SELECT key, id FROM chatbot_flow.node WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": keys},
    )
    return {str(key): int(node_id) for key, node_id in rows}


def _entry_transition(connection: Connection) -> tuple[int, int | None] | None:
    row = connection.execute(
        sa.text(
            "SELECT transition.id, transition.next_node_id FROM chatbot_flow.transition AS transition "
            "JOIN chatbot_flow.node AS node ON node.id = transition.node_id "
            "WHERE node.key = :node_key AND lower(transition.expected_value) = :expected"
        ),
        {"node_key": ENTRY_NODE, "expected": ENTRY_VALUE},
    ).first()
    return None if row is None else (int(row[0]), None if row[1] is None else int(row[1]))


def _upgrade_problems(connection: Connection) -> list[str]:
    """Everything the upgrade relies on, read before any write."""
    problems: list[str] = []
    placeholder = connection.execute(
        sa.text("SELECT id, CAST(type AS text), message FROM chatbot_flow.node WHERE key = 'paciente_imediato'")
    ).first()
    if placeholder is None:
        problems.append("o nó 'paciente_imediato' não existe (foi renomeado ou apagado no editor)")
    else:
        if placeholder[1] != "END" or placeholder[2] not in PLACEHOLDER_MESSAGES:
            problems.append("o nó 'paciente_imediato' foi editado: não é mais o fim com um dos textos provisórios conhecidos")
        outgoing = connection.scalar(
            sa.text("SELECT count(*) FROM chatbot_flow.transition WHERE node_id = :node_id"), {"node_id": placeholder[0]}
        )
        if outgoing:
            problems.append("o nó 'paciente_imediato' ganhou transições de saída")
    entry = _entry_transition(connection)
    if entry is None:
        problems.append("o botão 'Atendimento imediato' do nó 'paciente_tipo_atendimento' não existe mais")
    elif placeholder is not None and entry[1] != placeholder[0]:
        problems.append("o botão 'Atendimento imediato' não leva mais ao nó 'paciente_imediato'")
    taken = connection.execute(
        sa.text("SELECT key FROM chatbot_flow.node WHERE key IN :keys ORDER BY key").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(NEW_KEYS)},
    ).scalars().all()
    if taken:
        problems.append("já existem nós com os nomes usados pelo acolhimento imediato: " + ", ".join(taken))
    if connection.scalar(sa.text("SELECT count(*) FROM chatbot_flow.graph_revision WHERE status = 'PUBLISHED'")) == 0:
        problems.append("não há revisão publicada do fluxo")
    return problems


def _publish_revision(connection: Connection) -> None:
    """A new published version: workers reload the flow and drafts based on the old one are reported as stale."""
    connection.execute(
        sa.text(
            "INSERT INTO chatbot_flow.graph_revision (base_revision_id, status, version, created_at, updated_at, published_at) "
            "SELECT id, CAST('PUBLISHED' AS chatbot_flow.revision_status), version + 1, now(), now(), now() FROM chatbot_flow.graph_revision "
            "WHERE status = 'PUBLISHED' ORDER BY version DESC LIMIT 1"
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    problems = _upgrade_problems(connection)
    if problems:
        raise RuntimeError(
            "Migração 0019 (acolhimento imediato) não aplicada: o fluxo de produção é diferente do esperado. "
            "Nada foi alterado e o bot continua com a versão anterior. Diferenças: " + "; ".join(problems) + ". "
            "Desfaça essas mudanças no editor do fluxo (ou ajuste a migração) e rode o deploy de novo."
        )
    connection.execute(
        sa.text(
            "UPDATE chatbot_flow.node SET type = CAST('MESSAGE' AS chatbot_flow.node_type), title = :title, description = :description, "
            "message = :message WHERE key = 'paciente_imediato'"
        ),
        TRIAGE_1,
    )
    position = int(connection.scalar(sa.text("SELECT COALESCE(MAX(position), 0) FROM chatbot_flow.node")) or 0)
    for index, (key, node_type, title, description, message) in enumerate(NEW_NODES):
        connection.execute(
            sa.text(
                "INSERT INTO chatbot_flow.node (key, type, title, description, message, position, position_x, position_y) "
                "VALUES (:key, CAST(:type AS chatbot_flow.node_type), :title, :description, :message, :position, :x, :y)"
            ),
            {
                "key": key,
                "type": node_type,
                "title": title,
                "description": description,
                "message": message,
                "position": position + 1 + index,
                "x": 3200,
                "y": 200 + 180 * index,
            },
        )
    ids = _node_ids(connection)
    entry = _entry_transition(connection)
    if entry is None:  # already reported by _upgrade_problems
        raise RuntimeError("Transition 'Atendimento imediato' not found in paciente_tipo_atendimento")
    _insert_action(connection, entry[0], "immediate_gate", GATE_CONFIG, True)
    positions: dict[str, int] = {}
    for node_key, input_type, expected, button, target, actions in TRANSITIONS:
        transition_position = positions.get(node_key, 0)
        positions[node_key] = transition_position + 1
        transition_id = connection.execute(
            sa.text(
                "INSERT INTO chatbot_flow.transition (node_id, input_type, expected_value, button_label, next_node_id, position) "
                "VALUES (:node_id, CAST(:input_type AS chatbot_flow.input_type), :expected, :button, :target_id, :position) RETURNING id"
            ),
            {
                "node_id": ids[node_key],
                "input_type": input_type,
                "expected": expected,
                "button": button,
                "target_id": ids[target],
                "position": transition_position,
            },
        ).scalar_one()
        for action_key, config, is_required in actions:
            _insert_action(connection, int(transition_id), action_key, config, is_required)
    _publish_revision(connection)


def downgrade() -> None:
    connection = op.get_bind()
    ids = _node_ids(connection)
    node_ids = list(ids.values()) or [-1]
    # Every immediate_* action (the gate lives on a menu transition that stays) plus the actions on our own nodes.
    # Dependencies go first: the FK from action_dependency has no cascade.
    connection.execute(
        sa.text(
            "DELETE FROM chatbot_flow.action_dependency WHERE action_id IN ("
            "SELECT action.id FROM chatbot_flow.transition_action AS action JOIN chatbot_flow.transition AS transition "
            "ON transition.id = action.transition_id WHERE action.action_key LIKE 'immediate\\_%' OR transition.node_id IN :node_ids"
            ") OR depends_on_id IN ("
            "SELECT action.id FROM chatbot_flow.transition_action AS action JOIN chatbot_flow.transition AS transition "
            "ON transition.id = action.transition_id WHERE action.action_key LIKE 'immediate\\_%' OR transition.node_id IN :node_ids)"
        ).bindparams(sa.bindparam("node_ids", expanding=True)),
        {"node_ids": node_ids},
    )
    connection.execute(
        sa.text(
            "DELETE FROM chatbot_flow.transition_action WHERE id IN ("
            "SELECT action.id FROM chatbot_flow.transition_action AS action JOIN chatbot_flow.transition AS transition "
            "ON transition.id = action.transition_id WHERE action.action_key LIKE 'immediate\\_%' OR transition.node_id IN :node_ids)"
        ).bindparams(sa.bindparam("node_ids", expanding=True)),
        {"node_ids": node_ids},
    )
    if ids:
        # Keep the existing menu edge into paciente_imediato: only our own transitions go away.
        new_ids = [node_id for key, node_id in ids.items() if key != "paciente_imediato"] or [-1]
        connection.execute(
            sa.text("DELETE FROM chatbot_flow.transition WHERE node_id IN :node_ids OR next_node_id IN :new_ids").bindparams(
                sa.bindparam("node_ids", expanding=True), sa.bindparam("new_ids", expanding=True)
            ),
            {"node_ids": node_ids, "new_ids": new_ids},
        )
    connection.execute(
        sa.text("DELETE FROM chatbot_flow.node WHERE key IN :keys").bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(NEW_KEYS)},
    )
    connection.execute(
        sa.text(
            "UPDATE chatbot_flow.node SET type = CAST('END' AS chatbot_flow.node_type), title = :title, description = :description, "
            "message = :message WHERE key = 'paciente_imediato'"
        ),
        PLACEHOLDER,
    )
    _publish_revision(connection)
