"""Add an optional birth date to people."""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_add_birth_date_to_person"
down_revision: str | None = "0007_unify_message_media_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "person",
        sa.Column("birth_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("person", "birth_date")
