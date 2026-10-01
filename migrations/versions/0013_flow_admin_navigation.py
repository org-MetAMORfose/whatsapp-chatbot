"""Add persisted graph coordinates for chatbot nodes."""

import sqlalchemy as sa
from alembic import op

revision = "0013_flow_admin"
down_revision = "0012_seed_flow"
branch_labels = None
depends_on = None

SCHEMA = "chatbot_flow"


def upgrade() -> None:
    op.add_column(
        "node",
        sa.Column("position_x", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "node",
        sa.Column("position_y", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("node", "position_y", schema=SCHEMA)
    op.drop_column("node", "position_x", schema=SCHEMA)
