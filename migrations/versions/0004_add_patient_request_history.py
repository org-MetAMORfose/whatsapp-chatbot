"""Add patient request history and returning patient state.

Revision ID: 0004_add_patient_request_history
Revises: 0ce13cc54fd7
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_patient_request_history"
down_revision: str | None = "0ce13cc54fd7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE patient DROP CONSTRAINT IF EXISTS patient_person_id_key")

    op.add_column("patient", sa.Column("area", sa.String(), nullable=True))
    op.add_column(
        "patient",
        sa.Column("psychotherapy_approach", sa.String(), nullable=True),
    )
    op.add_column(
        "patient",
        sa.Column("professional_profile", sa.String(), nullable=True),
    )
    op.add_column("patient", sa.Column("price_range", sa.String(), nullable=True))

    # PostgreSQL cannot remove enum values safely; add the new value in place.
    op.execute("ALTER TYPE chatstate ADD VALUE IF NOT EXISTS 'RETURNING_PATIENT'")


def downgrade() -> None:
    # PostgreSQL cannot remove values from an enum. Rebuild the previous enum
    # only during downgrade; the upgrade keeps the existing enum in place.
    op.execute(
        "UPDATE person SET chat_state = NULL WHERE chat_state = 'RETURNING_PATIENT'"
    )
    op.execute(
        """
        CREATE TYPE chatstate_without_returning_patient AS ENUM (
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
        TYPE chatstate_without_returning_patient
        USING chat_state::text::chatstate_without_returning_patient
        """
    )
    op.execute("DROP TYPE chatstate")
    op.execute("ALTER TYPE chatstate_without_returning_patient RENAME TO chatstate")

    op.drop_column("patient", "price_range")
    op.drop_column("patient", "professional_profile")
    op.drop_column("patient", "psychotherapy_approach")
    op.drop_column("patient", "area")
