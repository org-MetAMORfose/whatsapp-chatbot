"""Unify message image and document references into one S3 media path."""

from __future__ import annotations

from typing import Sequence
from urllib.parse import unquote, urlparse

import sqlalchemy as sa
from alembic import op

revision: str = "0007_unify_message_media_path"
down_revision: str | None = "0006_rename_unknown_faq_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEDIA_PREFIXES = ("media/image/", "media/document/")


def _extract_media_path(value: str) -> str:
    parsed = urlparse(value)
    path = unquote(parsed.path if parsed.scheme else value)
    path = path.split("?", 1)[0].lstrip("/")

    media_index = path.find("media/")
    if media_index >= 0:
        path = path[media_index:]

    if not path.startswith(_MEDIA_PREFIXES):
        raise RuntimeError(f"Cannot extract an application media path from {value!r}")

    return path


def upgrade() -> None:
    op.add_column(
        "message_history",
        sa.Column("media_path", sa.String(), nullable=True),
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT id, image_url, document_url
            FROM message_history
            WHERE image_url IS NOT NULL OR document_url IS NOT NULL
            """
        )
    ).mappings()

    for row in rows:
        value = row["image_url"] or row["document_url"]
        media_path = _extract_media_path(str(value))
        connection.execute(
            sa.text(
                "UPDATE message_history SET media_path = :media_path WHERE id = :id"
            ),
            {"id": row["id"], "media_path": media_path},
        )

    op.drop_column("message_history", "image_url")
    op.drop_column("message_history", "document_url")


def downgrade() -> None:
    op.add_column(
        "message_history",
        sa.Column("image_url", sa.String(), nullable=True),
    )
    op.add_column(
        "message_history",
        sa.Column("document_url", sa.String(), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE message_history
            SET image_url = CASE
                    WHEN media_path LIKE 'media/image/%' THEN media_path
                    ELSE NULL
                END,
                document_url = CASE
                    WHEN media_path LIKE 'media/document/%' THEN media_path
                    ELSE NULL
                END
            """
        )
    )

    op.drop_column("message_history", "media_path")
