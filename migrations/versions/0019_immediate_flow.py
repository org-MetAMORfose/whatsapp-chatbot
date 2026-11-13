"""Immediate care: replace the "[URL em construção]" placeholder with the in-chat flow.

Converts `paciente_imediato` into the first triage question and adds the triage,
terms, duration, Pix, queue and terminal nodes. Copy lives in the database so the
panel's flow editor can adjust it. Downgrade restores the placeholder node.
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

TRIAGE_1 = {
    "title": "Triagem do atendimento imediato (1 de 2)",
    "description": "Primeira pergunta de segurança antes de qualquer cobrança.",
    "message": "Antes de continuar, duas perguntas rápidas.\n\nVocê está pensando em se machucar ou em tirar a própria vida?",
}

# (key, type, title, description, message)
NEW_NODES = (
    (
        "imediato_triagem_2",
        "MESSAGE",
        "Triagem do atendimento imediato (2 de 2)",
        "Segunda pergunta de segurança antes de qualquer cobrança.",
        "Você está passando agora por uma emergência, como uso de substâncias, violência ou uma crise intensa que precise de socorro?",
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
PAID_CONFIG = _route("immediate_paid", "imediato_na_fila")
DONE_CONFIG = _route("immediate_done", "imediato_encerrado")

# (node_key, input_type, expected_value, button_label, target_key, [(action_key, config, is_required)])
TRANSITIONS: tuple[tuple[str, str, str | None, str | None, str, list[tuple[str, dict[str, object] | None, bool]]], ...] = (
    ("paciente_imediato", "TEXT", "Não", "Não", "imediato_triagem_2", []),
    ("paciente_imediato", "TEXT", "Sim", "Sim", "imediato_emergencia", []),
    ("imediato_triagem_2", "TEXT", "Não", "Não", "imediato_termos", []),
    ("imediato_triagem_2", "TEXT", "Sim", "Sim", "imediato_emergencia", []),
    ("imediato_termos", "TEXT", "Aceito os termos", "Aceito os termos", "imediato_duracao", []),
    ("imediato_termos", "TEXT", "Não aceito", "Não aceito", "imediato_recusa", []),
    ("imediato_duracao", "TEXT", "30 minutos", "30 minutos", "imediato_pix", [("immediate_create_request", CREATE_REQUEST_CONFIG, True)]),
    ("imediato_duracao", "TEXT", "50 minutos", "50 minutos", "imediato_pix", [("immediate_create_request", CREATE_REQUEST_CONFIG, True)]),
    ("imediato_pix", "TEXT", "cancelar", None, "imediato_cancelado", [("immediate_cancel", None, True)]),
    ("imediato_pix", "AUTO", None, None, "imediato_pix", [("immediate_payment_status", PAID_CONFIG, False)]),
    ("imediato_na_fila", "AUTO", None, None, "imediato_na_fila", [("immediate_payment_status", DONE_CONFIG, False)]),
)

NEW_KEYS = tuple(node[0] for node in NEW_NODES)


def _node_ids(connection: Connection) -> dict[str, int]:
    rows = connection.execute(sa.text("SELECT key, id FROM chatbot_flow.node WHERE key = 'paciente_imediato' OR key LIKE 'imediato\\_%'"))
    return {str(key): int(node_id) for key, node_id in rows}


def upgrade() -> None:
    connection = op.get_bind()
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


def downgrade() -> None:
    connection = op.get_bind()
    ids = _node_ids(connection)
    node_ids = list(ids.values())
    if node_ids:
        connection.execute(
            sa.text(
                "DELETE FROM chatbot_flow.action_dependency WHERE action_id IN ("
                "SELECT action.id FROM chatbot_flow.transition_action AS action JOIN chatbot_flow.transition AS transition "
                "ON transition.id = action.transition_id WHERE transition.node_id IN :node_ids) OR depends_on_id IN ("
                "SELECT action.id FROM chatbot_flow.transition_action AS action JOIN chatbot_flow.transition AS transition "
                "ON transition.id = action.transition_id WHERE transition.node_id IN :node_ids)"
            ).bindparams(sa.bindparam("node_ids", expanding=True)),
            {"node_ids": node_ids},
        )
        connection.execute(
            sa.text(
                "DELETE FROM chatbot_flow.transition_action WHERE transition_id IN "
                "(SELECT id FROM chatbot_flow.transition WHERE node_id IN :node_ids)"
            ).bindparams(sa.bindparam("node_ids", expanding=True)),
            {"node_ids": node_ids},
        )
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
