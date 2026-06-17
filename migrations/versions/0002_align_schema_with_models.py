"""Align baseline schema with SQLAlchemy models."""

from __future__ import annotations

from typing import Sequence

from alembic import op

revision: str = "0002_align_schema_with_models"
down_revision: str | None = "0001_baseline_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "professional" DROP CONSTRAINT IF EXISTS "professional_person_id_fkey";
        ALTER TABLE "professional" DROP CONSTRAINT IF EXISTS "professional_status_id_fkey";
        ALTER TABLE "patient" DROP CONSTRAINT IF EXISTS "patient_person_id_fkey";
        ALTER TABLE "professional_patient" DROP CONSTRAINT IF EXISTS "professional_patient_professional_id_fkey";
        ALTER TABLE "professional_patient" DROP CONSTRAINT IF EXISTS "professional_patient_patient_id_fkey";
        ALTER TABLE "message_history" DROP CONSTRAINT IF EXISTS "message_history_person_id_fkey";
        ALTER TABLE "professional_status_history" DROP CONSTRAINT IF EXISTS "professional_status_history_professional_id_fkey";

        ALTER TABLE "person" DROP CONSTRAINT IF EXISTS "person_phone_number_key";

        CREATE TYPE "professionalstatus" AS ENUM (
          'REGISTER_PENDING',
          'UNDER_REVIEW',
          'APPROVED',
          'REJECTED',
          'PAYMENT_PENDING',
          'ACTIVE',
          'INACTIVE'
        );

        ALTER TABLE "professional_status_history"
          ALTER COLUMN "professional_status" TYPE "professionalstatus"
          USING CASE "professional_status"::text
            WHEN 'register_pending' THEN 'REGISTER_PENDING'::professionalstatus
            WHEN 'under_review' THEN 'UNDER_REVIEW'::professionalstatus
            WHEN 'approved' THEN 'APPROVED'::professionalstatus
            WHEN 'rejected' THEN 'REJECTED'::professionalstatus
            WHEN 'payment_pending' THEN 'PAYMENT_PENDING'::professionalstatus
            WHEN 'active' THEN 'ACTIVE'::professionalstatus
            WHEN 'inactive' THEN 'INACTIVE'::professionalstatus
            ELSE "professional_status"::text::professionalstatus
          END;

        DROP TYPE IF EXISTS "professional_status";

        ALTER TABLE "message_history" ALTER COLUMN "image_url" TYPE varchar;
        ALTER TABLE "message_history" ALTER COLUMN "document_url" TYPE varchar;

        ALTER TABLE "person"
          ADD CONSTRAINT "uq_person_phone_channel"
          UNIQUE ("phone_number", "channel");

        ALTER TABLE "professional"
          ADD CONSTRAINT "uq_professional_register"
          UNIQUE ("register_type", "professional_register");

        ALTER TABLE "professional_patient"
          ADD CONSTRAINT "uq_professional_patient"
          UNIQUE ("professional_id", "patient_id");

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id")
          ON DELETE CASCADE;

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_status_id_fkey"
          FOREIGN KEY ("status_id")
          REFERENCES "professional_status_history" ("id")
          ON DELETE RESTRICT;

        ALTER TABLE "patient"
          ADD CONSTRAINT "patient_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id")
          ON DELETE CASCADE;

        ALTER TABLE "professional_patient"
          ADD CONSTRAINT "professional_patient_professional_id_fkey"
          FOREIGN KEY ("professional_id")
          REFERENCES "professional" ("id")
          ON DELETE CASCADE;

        ALTER TABLE "professional_patient"
          ADD CONSTRAINT "professional_patient_patient_id_fkey"
          FOREIGN KEY ("patient_id")
          REFERENCES "patient" ("id")
          ON DELETE CASCADE;

        ALTER TABLE "message_history"
          ADD CONSTRAINT "message_history_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id");

        ALTER TABLE "professional_status_history"
          ADD CONSTRAINT "professional_status_history_professional_id_fkey"
          FOREIGN KEY ("professional_id")
          REFERENCES "professional" ("id")
          ON DELETE CASCADE;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE "professional" DROP CONSTRAINT IF EXISTS "professional_person_id_fkey";
        ALTER TABLE "professional" DROP CONSTRAINT IF EXISTS "professional_status_id_fkey";
        ALTER TABLE "patient" DROP CONSTRAINT IF EXISTS "patient_person_id_fkey";
        ALTER TABLE "professional_patient" DROP CONSTRAINT IF EXISTS "professional_patient_professional_id_fkey";
        ALTER TABLE "professional_patient" DROP CONSTRAINT IF EXISTS "professional_patient_patient_id_fkey";
        ALTER TABLE "message_history" DROP CONSTRAINT IF EXISTS "message_history_person_id_fkey";
        ALTER TABLE "professional_status_history" DROP CONSTRAINT IF EXISTS "professional_status_history_professional_id_fkey";

        ALTER TABLE "professional_patient" DROP CONSTRAINT IF EXISTS "uq_professional_patient";
        ALTER TABLE "professional" DROP CONSTRAINT IF EXISTS "uq_professional_register";
        ALTER TABLE "person" DROP CONSTRAINT IF EXISTS "uq_person_phone_channel";

        CREATE TYPE "professional_status" AS ENUM (
          'register_pending',
          'under_review',
          'approved',
          'rejected',
          'payment_pending',
          'active',
          'inactive'
        );

        ALTER TABLE "professional_status_history"
          ALTER COLUMN "professional_status" TYPE "professional_status"
          USING CASE "professional_status"::text
            WHEN 'REGISTER_PENDING' THEN 'register_pending'::professional_status
            WHEN 'UNDER_REVIEW' THEN 'under_review'::professional_status
            WHEN 'APPROVED' THEN 'approved'::professional_status
            WHEN 'REJECTED' THEN 'rejected'::professional_status
            WHEN 'PAYMENT_PENDING' THEN 'payment_pending'::professional_status
            WHEN 'ACTIVE' THEN 'active'::professional_status
            WHEN 'INACTIVE' THEN 'inactive'::professional_status
            ELSE "professional_status"::text::professional_status
          END;

        DROP TYPE IF EXISTS "professionalstatus";

        ALTER TABLE "message_history" ALTER COLUMN "image_url" TYPE text;
        ALTER TABLE "message_history" ALTER COLUMN "document_url" TYPE text;

        ALTER TABLE "person"
          ADD CONSTRAINT "person_phone_number_key"
          UNIQUE ("phone_number");

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "professional"
          ADD CONSTRAINT "professional_status_id_fkey"
          FOREIGN KEY ("status_id")
          REFERENCES "professional_status_history" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "patient"
          ADD CONSTRAINT "patient_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "professional_patient"
          ADD CONSTRAINT "professional_patient_professional_id_fkey"
          FOREIGN KEY ("professional_id")
          REFERENCES "professional" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "professional_patient"
          ADD CONSTRAINT "professional_patient_patient_id_fkey"
          FOREIGN KEY ("patient_id")
          REFERENCES "patient" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "message_history"
          ADD CONSTRAINT "message_history_person_id_fkey"
          FOREIGN KEY ("person_id")
          REFERENCES "person" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;

        ALTER TABLE "professional_status_history"
          ADD CONSTRAINT "professional_status_history_professional_id_fkey"
          FOREIGN KEY ("professional_id")
          REFERENCES "professional" ("id")
          DEFERRABLE INITIALLY IMMEDIATE;
        """
    )
