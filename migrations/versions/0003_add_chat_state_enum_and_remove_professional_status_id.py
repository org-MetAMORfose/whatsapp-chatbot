"""Add chat state enum and remove professional status id."""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0003_add_chat_state_enum"
down_revision: str | None = "0002_align_schema_with_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "person" DROP COLUMN "chat_state";

        CREATE TYPE "chatstate" AS ENUM (
          'AGENT_RUNNING',
          'AGENT_STOP',
          'FEEDBACK',
          'QUESTION',
          'PROFESSIONAL_SUPPORT',
          'NEW_PATIENT',
          'PAYMENT_RENEWAL',
          'PROFESSIONAL_REGISTRATION'
        );

        ALTER TABLE "person"
          ADD COLUMN "chat_state" chatstate NOT NULL DEFAULT 'AGENT_RUNNING';

        ALTER TABLE "professional"
          DROP CONSTRAINT IF EXISTS "professional_status_id_fkey";

        ALTER TABLE "professional"
          DROP CONSTRAINT IF EXISTS "professional_status_id_key";

        ALTER TABLE "professional" DROP COLUMN "status_id";
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE "professional" ADD COLUMN "status_id" integer;

        UPDATE "professional" AS p
        SET "status_id" = latest.id
        FROM (
          SELECT DISTINCT ON ("professional_id")
            "professional_id",
            id
          FROM "professional_status_history"
          ORDER BY "professional_id", "created_at" DESC, id DESC
        ) AS latest
        WHERE latest."professional_id" = p.id;

        ALTER TABLE "professional"
          ALTER COLUMN "status_id" SET NOT NULL;

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_status_id_key" UNIQUE ("status_id");

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_status_id_fkey"
          FOREIGN KEY ("status_id")
          REFERENCES "professional_status_history" ("id")
          ON DELETE RESTRICT;

        ALTER TABLE "person" DROP COLUMN "chat_state";
        DROP TYPE IF EXISTS "chatstate";

        ALTER TABLE "person"
          ADD COLUMN "chat_state" varchar NOT NULL DEFAULT 'START';
        """
    )
