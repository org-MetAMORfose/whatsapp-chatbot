"""Create database-backed chatbot flow and scope patients to matching cycles."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_chatbot_flow"
down_revision = "0010_matching"
branch_labels = None
depends_on = None

SCHEMA = "chatbot_flow"


def upgrade() -> None:
    op.execute(sa.text(f"CREATE SCHEMA {SCHEMA}"))
    node_type = postgresql.ENUM("START", "MESSAGE", "END", name="node_type", schema=SCHEMA, create_type=False)
    input_type = postgresql.ENUM(
        "TEXT", "EMAIL", "DATE", "NUMBER", "IMAGE", "DOCUMENT", "VIDEO", "AUTO",
        name="input_type", schema=SCHEMA, create_type=False,
    )
    node_type.create(op.get_bind(), checkfirst=False)
    input_type.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "node",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(), nullable=False, unique=True),
        sa.Column("type", node_type, nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "transition",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_type", input_type, nullable=False),
        sa.Column("expected_value", sa.String()),
        sa.Column("button_label", sa.String()),
        sa.Column("next_node_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.node.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("node_id", "position", name="uq_transition_node_position"),
        schema=SCHEMA,
    )
    op.create_table(
        "transition_action",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("transition_id", sa.Integer(), sa.ForeignKey(f"{SCHEMA}.transition.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_key", sa.String(), nullable=False),
        sa.Column("config", postgresql.JSONB()),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema=SCHEMA,
    )
    op.create_table(
        "input_error_message",
        sa.Column("input_type", input_type, primary_key=True),
        sa.Column("message", sa.Text(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_chatbot_flow_revision_singleton"),
        schema=SCHEMA,
    )
    revision_table = sa.table(
        "revision",
        sa.column("id", sa.Integer()),
        sa.column("version", sa.BigInteger()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        schema=SCHEMA,
    )
    op.bulk_insert(revision_table, [{"id": 1, "version": 1, "updated_at": datetime.now(UTC)}])
    op.drop_constraint("matching_slot_patient_id_key", "matching_slot", type_="unique")
    op.create_unique_constraint(
        "uq_matching_slot_patient_cycle", "matching_slot", ["patient_id", "cycle_id"]
    )


def downgrade() -> None:
    duplicate = op.get_bind().scalar(sa.text(
        "SELECT 1 FROM matching_slot GROUP BY patient_id HAVING count(*) > 1 LIMIT 1"
    ))
    if duplicate:
        raise RuntimeError("Cannot restore global patient uniqueness while a patient belongs to multiple cycles")
    op.drop_constraint("uq_matching_slot_patient_cycle", "matching_slot", type_="unique")
    op.create_unique_constraint("matching_slot_patient_id_key", "matching_slot", ["patient_id"])
    op.drop_table("revision", schema=SCHEMA)
    op.drop_table("input_error_message", schema=SCHEMA)
    op.drop_table("transition_action", schema=SCHEMA)
    op.drop_table("transition", schema=SCHEMA)
    op.drop_table("node", schema=SCHEMA)
    op.execute(sa.text(f"DROP TYPE {SCHEMA}.input_type"))
    op.execute(sa.text(f"DROP TYPE {SCHEMA}.node_type"))
    op.execute(sa.text(f"DROP SCHEMA {SCHEMA}"))
