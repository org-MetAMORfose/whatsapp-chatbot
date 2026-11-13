"""Immediate care: request table and professional availability flag.

Revision ID: 0018_immediate_care
Revises: 0017_intake_matching_actions
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_immediate_care"
down_revision = "0017_intake_matching_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "immediate_request",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_person_id", sa.Integer(), sa.ForeignKey("person.id"), nullable=False),
        sa.Column("professional_person_id", sa.Integer(), sa.ForeignKey("person.id")),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("pix_txid", sa.String(), unique=True),
        sa.Column("pix_copia_cola", sa.Text()),
        sa.Column("pix_e2e_id", sa.String()),
        sa.Column("pix_refund_id", sa.String()),
        sa.Column("room_url", sa.Text()),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
        sa.Column("refund_failed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('awaiting_payment', 'queued', 'accepted', 'expired', 'cancelled')",
            name="ck_immediate_request_status",
        ),
    )
    op.create_index("ix_immediate_request_status_expires", "immediate_request", ["status", "expires_at"])
    op.create_index("ix_immediate_request_patient", "immediate_request", ["patient_person_id"])
    op.add_column(
        "professional",
        sa.Column("available_for_immediate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("professional", sa.Column("immediate_availability_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("professional", "immediate_availability_updated_at")
    op.drop_column("professional", "available_for_immediate")
    op.drop_index("ix_immediate_request_patient", table_name="immediate_request")
    op.drop_index("ix_immediate_request_status_expires", table_name="immediate_request")
    op.drop_table("immediate_request")
