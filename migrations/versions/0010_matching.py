"""Matching cycles and immutable allocations replace professional_patient."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_matching"
down_revision = "0009_event_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Do not silently discard real historical associations.
    if connection.scalar(sa.text("SELECT count(*) FROM professional_patient")):
        raise RuntimeError("professional_patient contains data; export and reconcile links before this migration")
    op.add_column("professional", sa.Column("gender", sa.String(), nullable=True))
    op.add_column("professional", sa.Column("minority_group", sa.String(), nullable=True))
    op.create_table("matching_cycle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professional.id"), nullable=False),
        sa.Column("type", sa.Enum("REGULAR", "REPLACEMENT", name="matching_cycle_type"), nullable=False),
        sa.Column("promised_patients", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("promised_patients > 0", name="ck_matching_capacity"),
        sa.CheckConstraint("deadline_at > starts_at", name="ck_matching_dates"))
    op.create_index("ix_matching_cycle_deadline_at", "matching_cycle", ["deadline_at"])
    op.create_table("matching_slot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cycle_id", sa.Integer(), sa.ForeignKey("matching_cycle.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient.id"), nullable=False, unique=True),
        sa.Column("compatibility_score", sa.Float(), nullable=False),
        sa.Column("urgency_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float(), nullable=False),
        sa.Column("score_breakdown", postgresql.JSONB(), nullable=False),
        sa.Column("algorithm_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_matching_slot_cycle_id", "matching_slot", ["cycle_id"])
    op.drop_table("professional_patient")


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM matching_slot")):
        raise RuntimeError("Cannot discard matching history; restore a backup or migrate allocations explicitly")
    op.drop_table("matching_slot")
    op.drop_table("matching_cycle")
    op.execute("DROP FUNCTION IF EXISTS guard_matching_slot(); DROP FUNCTION IF EXISTS guard_matching_cycle(); DROP TYPE matching_cycle_type")
    op.drop_column("professional", "minority_group")
    op.drop_column("professional", "gender")
    op.create_table("professional_patient",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("professional_id", sa.Integer(), sa.ForeignKey("professional.id", ondelete="CASCADE"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("professional_id", "patient_id", name="uq_professional_patient"))
