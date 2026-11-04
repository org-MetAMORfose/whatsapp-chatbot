"""Wire matching answers into the published flow without changing the schema.

Custom specialty/declaration nodes are matched by key and may be absent from a
fresh installation. Downgrade preserves editor data, as in revision 0016.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "0017_intake_matching_actions"
down_revision = "0016_optional_registration"
branch_labels = None
depends_on = None

ACTION_NODES = (
    (
        "redis_update_patient_psychotherapy_specialties",
        ("Qual especialidade quer ser atendido", "Qual outra especialidade quer ser atendido?"),
    ),
    (
        "redis_update_professional_psychotherapy_specialties",
        ("Qual especialidade quer atender?", "Qual outra especialidade quer atender?"),
    ),
    (
        "redis_update_patient_preferred_gender",
        ("paciente_psico_perfil", "paciente_corrigir_perfil"),
    ),
    (
        "redis_update_patient_preferred_race",
        (
            "Autodeclaração - por qual profissional você quer ser atendido?",
            "Correção Autodeclaração - por qual profissional você quer ser atendido?",
        ),
    ),
    (
        "redis_get_patient_stage_summary",
        ("Correção Autodeclaração - por qual profissional você quer ser atendido?",),
    ),
)


def _add_actions(connection: Connection, action_key: str, node_keys: tuple[str, ...]) -> int:
    result = connection.execute(
        sa.text("""
            INSERT INTO chatbot_flow.transition_action (transition_id, action_key, config, is_required)
            SELECT transition.id, :action_key, '{}'::jsonb, false
            FROM chatbot_flow.transition AS transition
            JOIN chatbot_flow.node AS node ON node.id = transition.node_id
            WHERE node.key IN :node_keys
              AND transition.input_type = 'TEXT'
              AND (
                  :gender_only = false OR lower(transition.expected_value) IN (
                      'homem', 'mulher', 'não binário', 'nao binario', 'sem preferência', 'sem preferencia'
                  )
              )
              AND NOT EXISTS (
                  SELECT 1 FROM chatbot_flow.transition_action AS action
                  WHERE action.transition_id = transition.id AND action.action_key = :action_key
              )
        """).bindparams(sa.bindparam("node_keys", expanding=True)),
        {"action_key": action_key, "node_keys": node_keys, "gender_only": action_key == "redis_update_patient_preferred_gender"},
    )
    return result.rowcount


def upgrade() -> None:
    connection = op.get_bind()
    # Replace in place so the gender answer is stored before summary actions.
    # The combined legacy action would otherwise clear race/identity preferences.
    result = connection.execute(sa.text("""
        UPDATE chatbot_flow.transition_action AS action
        SET action_key = 'redis_update_patient_preferred_gender',
            config = COALESCE(action.config, '{}'::jsonb)
        FROM chatbot_flow.transition AS transition, chatbot_flow.node AS node
        WHERE action.transition_id = transition.id
          AND transition.node_id = node.id
          AND node.key IN ('paciente_psico_perfil', 'paciente_corrigir_perfil')
          AND lower(transition.expected_value) IN (
              'homem', 'mulher', 'não binário', 'nao binario', 'sem preferência', 'sem preferencia'
          )
          AND action.action_key = 'redis_update_patient_professional_profile'
    """))
    changed = result.rowcount
    for action_key, node_keys in ACTION_NODES:
        changed += _add_actions(connection, action_key, node_keys)

    if changed:
        # A new version makes existing editor drafts stale rather than silently
        # allowing them to overwrite the migrated graph. Worker startup refreshes Redis.
        connection.execute(sa.text("""
            INSERT INTO chatbot_flow.graph_revision
                (base_revision_id, status, version, created_at, updated_at, published_at)
            SELECT id, 'PUBLISHED', version + 1, now(), now(), now()
            FROM chatbot_flow.graph_revision
            WHERE status = 'PUBLISHED'
            ORDER BY version DESC LIMIT 1
        """))


def downgrade() -> None:
    """Preserve configured actions; restore a backup to undo this data migration."""
