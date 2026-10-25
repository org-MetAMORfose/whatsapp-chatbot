import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.base import Base
from app.domain.db.chatbot_flow_model import (
    FlowActionDependencyModel,
    FlowGraphChangeModel,
    FlowGraphRevisionModel,
    FlowNodeModel,
    FlowTransitionActionModel,
    FlowTransitionModel,
)
from app.domain.enum.chatbot_flow import ChangeEntityType, ChangeOperation, InputType, NodeType, RevisionStatus


def snapshot(session_factory: sessionmaker[Session]):
    with session_factory() as session:
        return {
            table.name: [dict(row) for row in session.execute(select(table).order_by(*table.primary_key)).mappings()]
            for table in Base.metadata.sorted_tables
            if table.schema == "chatbot_flow"
        }


@pytest.mark.parametrize("already_adjusted", [False, True])
def test_registration_migration_preserves_unrelated_actions_and_editor_data(
    session_factory: sessionmaker[Session],
    already_adjusted: bool,
) -> None:
    registration_keys = (
        "redis_update_patient_name",
        "redis_update_professional_psychotherapy_specialties",
        "postgres_route_patient_registration",
        "postgres_set_returning_patient_state",
        "postgres_set_professional_registration_state",
        "sheets_register_patient",
    )
    other_keys = (
        "faq_process_question",
        "postgres_set_payment_renewal_state",
        "postgres_set_professional_support_state",
        "postgres_set_manual_chat_mode",
        "sheets_store_answer",
        "redis_update_patient_custom_action",
    )
    with session_factory() as session, session.begin():
        start = FlowNodeModel(id=901, key="start", type=NodeType.START, title="Início", message="Olá", position=0)
        end = FlowNodeModel(id=902, key="end", type=NodeType.END, title="Fim", message="Fim", position=1)
        session.add_all([start, end])
        session.flush()
        transition = FlowTransitionModel(id=903, node_id=start.id, input_type=InputType.AUTO, next_node_id=end.id, position=0)
        session.add(transition)
        session.flush()
        actions = {
            key: FlowTransitionActionModel(
                id=1001 + index,
                transition_id=transition.id,
                action_key=key,
                is_required=(not already_adjusted and key != "sheets_register_patient") if key in registration_keys else True,
            )
            for index, key in enumerate((*registration_keys, *other_keys))
        }
        session.add_all(actions.values())
        session.flush()
        session.add(FlowActionDependencyModel(
            id=1101, action_id=actions[other_keys[1]].id, depends_on_id=actions[other_keys[0]].id,
        ))
        if not already_adjusted:
            for index, (action, prerequisite) in enumerate((
                (registration_keys[0], registration_keys[1]),
                (other_keys[0], registration_keys[0]),
                (registration_keys[1], other_keys[2]),
            )):
                session.add(FlowActionDependencyModel(id=1201 + index, action_id=actions[action].id, depends_on_id=actions[prerequisite].id))
        session.add(FlowGraphRevisionModel(id=801, status=RevisionStatus.PUBLISHED, version=7))
        session.flush()
        session.add(FlowGraphRevisionModel(id=802, status=RevisionStatus.DRAFT, base_revision_id=801))
        session.flush()
        session.add(FlowGraphChangeModel(
            revision_id=802,
            entity_type=ChangeEntityType.NODE,
            entity_id=start.id,
            operation=ChangeOperation.UPDATE,
            previous_value={"message": "Olá"},
            new_value={"message": "Mensagem em edição"},
        ))

    expected = deepcopy(snapshot(session_factory))
    for action in expected["transition_action"]:
        if action["action_key"] in registration_keys:
            action["is_required"] = False
    expected["action_dependency"] = [row for row in expected["action_dependency"] if row["id"] == 1101]
    migration = runpy.run_path(str(Path(__file__).parents[2] / "migrations/versions/0016_optional_registration_actions.py"))
    for operation in ("upgrade", "upgrade", "downgrade"):
        with session_factory() as session, session.begin():
            with Operations.context(MigrationContext.configure(session.connection())):
                migration[operation]()
        assert snapshot(session_factory) == expected
