"""Add JSONB matching profiles and backfill from legacy registration columns."""

import json
from types import SimpleNamespace

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.domain.matching.profile import from_legacy_patient, from_legacy_professional

revision = "0015_matching_json_profiles"
down_revision = "0014_patient_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("professional", sa.Column("matching_profile", postgresql.JSONB(), nullable=False,
                                             server_default=sa.text("'{}'::jsonb")))
    op.add_column("patient", sa.Column("matching_request", postgresql.JSONB(), nullable=False,
                                        server_default=sa.text("'{}'::jsonb")))
    connection = op.get_bind()
    for row in connection.execute(sa.text("SELECT id, area, approach, gender, minority_group FROM professional")):
        record = SimpleNamespace(**row._mapping)
        connection.execute(sa.text("UPDATE professional SET matching_profile = CAST(:value AS jsonb) WHERE id = :id"),
                           {"id": record.id, "value": json.dumps(from_legacy_professional(record), ensure_ascii=False)})
    for row in connection.execute(sa.text("SELECT id, area, psychotherapy_approach, professional_profile FROM patient")):
        record = SimpleNamespace(**row._mapping)
        connection.execute(sa.text("UPDATE patient SET matching_request = CAST(:value AS jsonb) WHERE id = :id"),
                           {"id": record.id, "value": json.dumps(from_legacy_patient(record), ensure_ascii=False)})
    op.create_index("ix_professional_matching_areas", "professional", ["matching_profile"], postgresql_using="gin")
    op.create_index("ix_patient_matching_request", "patient", ["matching_request"], postgresql_using="gin")


def downgrade() -> None:
    connection = op.get_bind()
    for row in connection.execute(sa.text(
        "SELECT id, area, approach, gender, minority_group, matching_profile FROM professional"
    )):
        record = SimpleNamespace(**row._mapping)
        if record.matching_profile != from_legacy_professional(record):
            raise RuntimeError("Professional JSON contains data absent from legacy columns")
    for row in connection.execute(sa.text(
        "SELECT id, area, psychotherapy_approach, professional_profile, matching_request FROM patient"
    )):
        record = SimpleNamespace(**row._mapping)
        if record.matching_request != from_legacy_patient(record):
            raise RuntimeError("Patient JSON contains data absent from legacy columns")
    op.drop_index("ix_patient_matching_request", table_name="patient")
    op.drop_index("ix_professional_matching_areas", table_name="professional")
    op.drop_column("patient", "matching_request")
    op.drop_column("professional", "matching_profile")
