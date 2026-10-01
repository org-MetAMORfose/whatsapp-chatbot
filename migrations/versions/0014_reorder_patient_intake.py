"""Collect psychotherapy preferences before the patient's birth date."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision = "0014_patient_order"
down_revision = "0013_flow_admin"
branch_labels = None
depends_on = None


def _set_targets(
    connection: Connection,
    *,
    source_key: str,
    target_key: str,
) -> int:
    result = connection.execute(
        sa.text(
            """
            UPDATE chatbot_flow.transition AS transition
            SET next_node_id = target.id
            FROM chatbot_flow.node AS source, chatbot_flow.node AS target
            WHERE transition.node_id = source.id
              AND source.key = :source_key
              AND target.key = :target_key
            """
        ),
        {"source_key": source_key, "target_key": target_key},
    )
    return result.rowcount


def _set_birth_date_config(connection: Connection, config: str | None) -> int:
    result = connection.execute(
        sa.text(
            """
            UPDATE chatbot_flow.transition_action AS action
            SET config = CAST(:config AS jsonb)
            FROM chatbot_flow.transition AS transition,
                 chatbot_flow.node AS node
            WHERE action.transition_id = transition.id
              AND transition.node_id = node.id
              AND node.key = 'paciente_data_nascimento'
              AND action.action_key = 'redis_update_patient_birth_date'
            """
        ),
        {"config": config},
    )
    return result.rowcount


def _assert_counts(counts: Sequence[tuple[str, int, int]]) -> None:
    failures = [f"{name}: expected {expected}, updated {actual}" for name, actual, expected in counts if actual != expected]
    if failures:
        raise RuntimeError("Patient flow migration did not match the seeded graph: " + "; ".join(failures))


def upgrade() -> None:
    connection = op.get_bind()
    _assert_counts(
        (
            (
                "psychotherapy approach transitions",
                _set_targets(
                    connection,
                    source_key="paciente_psico_abordagem",
                    target_key="paciente_psico_perfil",
                ),
                3,
            ),
            (
                "professional profile transitions",
                _set_targets(
                    connection,
                    source_key="paciente_psico_perfil",
                    target_key="paciente_data_nascimento",
                ),
                5,
            ),
            ("birth date action config", _set_birth_date_config(connection, None), 1),
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    config = """
        {
          "config_type": "action_transition",
          "source": {
            "type": "action_result",
            "field": "patient_area"
          },
          "operator": "eq",
          "value": "psicoterapia",
          "target_node_key": "paciente_psico_perfil"
        }
    """
    _assert_counts(
        (
            (
                "psychotherapy approach transitions",
                _set_targets(
                    connection,
                    source_key="paciente_psico_abordagem",
                    target_key="paciente_data_nascimento",
                ),
                3,
            ),
            (
                "professional profile transitions",
                _set_targets(
                    connection,
                    source_key="paciente_psico_perfil",
                    target_key="paciente_faixa_valor",
                ),
                5,
            ),
            (
                "birth date action config",
                _set_birth_date_config(connection, config),
                1,
            ),
        )
    )
