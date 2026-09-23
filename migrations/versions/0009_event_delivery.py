"""Add durable processing receipts and a generic transactional outbox."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_event_delivery"
down_revision = "0008_add_birth_date_to_person"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'processing', 'sent', 'failed')", name="ck_outbox_status"),
    )
    op.create_index("ix_outbox_ready", "outbox", ["status", "available_at"])
    op.create_index("ix_outbox_lease", "outbox", ["status", "locked_until"])
    op.create_table(
        "inbox", sa.Column("id", sa.String(), primary_key=True),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inbox")
    op.drop_table("outbox")
