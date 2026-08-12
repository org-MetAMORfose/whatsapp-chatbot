"""Rename the unknown FAQ outcome to abandoned.

Revision ID: 0006_rename_unknown_faq_outcome
Revises: 0005_add_faq_analytics
"""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0006_rename_unknown_faq_outcome"
down_revision: str | None = "0005_add_faq_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE faq_session_outcome "
        "RENAME VALUE 'UNKNOWN' TO 'ABANDONED'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TYPE faq_session_outcome "
        "RENAME VALUE 'ABANDONED' TO 'UNKNOWN'"
    )
