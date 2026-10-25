"""Make registration actions removable without changing the chatbot routes.

Downgrade intentionally preserves this data change: previous flags and deleted
dependencies cannot be inferred after administrators edit the graph.
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_optional_registration"
down_revision = "0015_matching_json_profiles"
branch_labels = None
depends_on = None

# Freeze the audited keys here instead of importing the evolving action catalog.
REGISTRATION_ACTION_KEYS = (
    "postgres_register_new_patient_request",
    "postgres_register_professional_application",
    "postgres_register_returning_patient_from_last_request",
    "postgres_route_patient_preference_update",
    "postgres_route_patient_registration",
    "postgres_set_new_patient_state",
    "postgres_set_professional_registration_state",
    "postgres_set_returning_patient_state",
    "postgres_update_person_name",
    "postgres_update_professional_qualification",
    "redis_correct_professional_birth_date",
    "redis_create_professional_stage",
    "redis_get_patient_stage_summary",
    "redis_get_professional_stage_summary",
    "redis_update_patient_area",
    "redis_update_patient_birth_date",
    "redis_update_patient_name",
    "redis_update_patient_preferred_gender",
    "redis_update_patient_preferred_race",
    "redis_update_patient_prefers_lgbtqiapn_plus",
    "redis_update_patient_price_range",
    "redis_update_patient_professional_profile",
    "redis_update_patient_psychotherapy_approach",
    "redis_update_patient_psychotherapy_specialties",
    "redis_update_professional_approach",
    "redis_update_professional_area",
    "redis_update_professional_birth_date",
    "redis_update_professional_council_registration",
    "redis_update_professional_council_registration_document",
    "redis_update_professional_email",
    "redis_update_professional_gender",
    "redis_update_professional_lgbtqiapn_plus",
    "redis_update_professional_minority_group",
    "redis_update_professional_name",
    "redis_update_professional_psychotherapy_specialties",
    "redis_update_professional_race",
    "redis_update_professional_video_tool",
    "sheets_register_patient",
    "sheets_register_professional",
)


def upgrade() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData(schema="chatbot_flow")
    actions = sa.Table(
        "transition_action",
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("action_key", sa.String()),
        sa.Column("is_required", sa.Boolean()),
    )
    dependencies = sa.Table(
        "action_dependency",
        metadata,
        sa.Column("action_id", sa.Integer()),
        sa.Column("depends_on_id", sa.Integer()),
    )
    registration = actions.c.action_key.in_(REGISTRATION_ACTION_KEYS)
    connection.execute(actions.update().where(registration, actions.c.is_required.is_(True)).values(is_required=False))
    registration_ids = sa.select(actions.c.id).where(registration)
    connection.execute(dependencies.delete().where(sa.or_(
        dependencies.c.action_id.in_(registration_ids),
        dependencies.c.depends_on_id.in_(registration_ids),
    )))


def downgrade() -> None:
    """Keep editor configuration; restore an environment backup to undo it."""
