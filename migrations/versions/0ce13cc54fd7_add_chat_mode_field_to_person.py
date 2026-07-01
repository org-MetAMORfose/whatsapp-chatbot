"""Add chat_mode field to person."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0ce13cc54fd7"
down_revision: str | None = "0003_add_chat_state_enum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


chat_mode_enum = sa.Enum("AUTOMATIC", "MANUAL", name="chatmode")


def upgrade() -> None:
    chat_mode_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "person",
        sa.Column("chat_mode", chat_mode_enum, nullable=False, server_default="AUTOMATIC"),
    )
    op.alter_column("person", "chat_mode", server_default=None)

    op.execute("ALTER TABLE person ALTER COLUMN chat_state DROP DEFAULT")
    op.execute("ALTER TABLE person ALTER COLUMN chat_state DROP NOT NULL")
    op.execute("UPDATE person SET chat_state = NULL WHERE chat_state IN ('AGENT_RUNNING', 'AGENT_STOP')")
    op.execute(
        """
        CREATE TYPE chatstate_new AS ENUM (
            'FEEDBACK',
            'QUESTION',
            'PROFESSIONAL_SUPPORT',
            'NEW_PATIENT',
            'PAYMENT_RENEWAL',
            'PROFESSIONAL_REGISTRATION'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE person
        ALTER COLUMN chat_state
        TYPE chatstate_new
        USING chat_state::text::chatstate_new
        """
    )
    op.execute("DROP TYPE chatstate")
    op.execute("ALTER TYPE chatstate_new RENAME TO chatstate")

    op.alter_column(
        "person",
        "chat_state",
        existing_type=postgresql.ENUM(
            "FEEDBACK",
            "QUESTION",
            "PROFESSIONAL_SUPPORT",
            "NEW_PATIENT",
            "PAYMENT_RENEWAL",
            "PROFESSIONAL_REGISTRATION",
            name="chatstate",
        ),
        nullable=True,
        existing_server_default=None,
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE TYPE chatstate_old AS ENUM (
            'AGENT_RUNNING',
            'AGENT_STOP',
            'FEEDBACK',
            'QUESTION',
            'PROFESSIONAL_SUPPORT',
            'NEW_PATIENT',
            'PAYMENT_RENEWAL',
            'PROFESSIONAL_REGISTRATION'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE person
        ALTER COLUMN chat_state
        TYPE chatstate_old
        USING chat_state::text::chatstate_old
        """
    )
    op.execute("DROP TYPE chatstate")
    op.execute("ALTER TYPE chatstate_old RENAME TO chatstate")

    op.execute("UPDATE person SET chat_state = 'AGENT_RUNNING' WHERE chat_state IS NULL")
    op.execute("ALTER TABLE person ALTER COLUMN chat_state SET DEFAULT 'AGENT_RUNNING'::chatstate")
    op.execute("ALTER TABLE person ALTER COLUMN chat_state SET NOT NULL")

    op.drop_column("person", "chat_mode")
    chat_mode_enum.drop(op.get_bind(), checkfirst=True)
