"""Keep matching business rules in the application, including existing installations."""
from alembic import op

revision = "0011_remove_matching_triggers"
down_revision = "0010_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      DROP TRIGGER IF EXISTS matching_slot_guard ON matching_slot;
      DROP TRIGGER IF EXISTS matching_cycle_guard ON matching_cycle;
      DROP FUNCTION IF EXISTS guard_matching_slot();
      DROP FUNCTION IF EXISTS guard_matching_cycle();
    """)


def downgrade() -> None:
    # Business validation stays in code; do not reintroduce removed triggers.
    pass
