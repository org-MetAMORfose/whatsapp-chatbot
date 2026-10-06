from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.chatbot_flow_model import (
    FlowGraphChangeModel,
    FlowGraphRevisionModel,
    FlowNodeModel,
    FlowTransitionActionModel,
    FlowTransitionModel,
)
from app.domain.enum.chatbot_flow import (
    ChangeEntityType,
    ChangeOperation,
    InputType,
    NodeType,
    RevisionStatus,
)
from app.services.chatbot_flow_admin_service import (
    ChatFlowAdminService,
    DraftChangeInput,
    FlowCachePublishError,
    InvalidFlowChangeError,
)


def seed_flow(session_factory: sessionmaker[Session]) -> tuple[int, int]:
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        start = FlowNodeModel(
            key="start",
            type=NodeType.START,
            title="Início",
            message="Início",
            position=0,
        )
        message = FlowNodeModel(
            key="message",
            type=NodeType.MESSAGE,
            title="Mensagem",
            message="Mensagem original",
            position=1,
        )
        end = FlowNodeModel(
            key="end",
            type=NodeType.END,
            title="Fim",
            message="Fim",
            position=2,
        )
        session.add_all([start, message, end])
        session.flush()
        first = FlowTransitionModel(
            node_id=start.id,
            input_type=InputType.AUTO,
            next_node_id=message.id,
            position=0,
        )
        second = FlowTransitionModel(
            node_id=message.id,
            input_type=InputType.AUTO,
            next_node_id=end.id,
            position=0,
        )
        session.add_all([first, second])
        session.flush()
        session.add(
            FlowTransitionActionModel(
                transition_id=second.id,
                action_key="required_action",
                is_required=True,
            )
        )
        revision = FlowGraphRevisionModel(
            status=RevisionStatus.PUBLISHED,
            version=1,
            created_at=now,
            updated_at=now,
            published_at=now,
        )
        session.add(revision)
        session.flush()
        return revision.id, message.id


def test_accepts_catalog_and_internal_actions() -> None:
    ChatFlowAdminService._validate_action(
        {"action_key": "postgres_set_question_state", "config": None}
    )
    ChatFlowAdminService._validate_action(
        {
            "action_key": "custom_action",
            "config": {"config_type": "custom", "mode": "copy"},
        }
    )

    with pytest.raises(InvalidFlowChangeError):
        ChatFlowAdminService._validate_action(
            {"action_key": "", "config": None}
        )

    ChatFlowAdminService._validate_action(
        {
            "action_key": "sheets_store_answer",
            "config": {
                "config_type": "sheets_store_answer",
                "tab": "Pacientes",
                "column": "G",
            },
        }
    )


def test_can_copy_internal_action_to_a_new_transition(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, _ = seed_flow(session_factory)
    service = ChatFlowAdminService(session_factory, AsyncMock())
    draft = service.create_draft(published_id)
    graph = service.get_graph(draft["id"])
    source_action = next(
        action
        for action in graph["transition_actions"]
        if action["action_key"] == "required_action"
    )
    source_transition = next(
        transition
        for transition in graph["transitions"]
        if transition["id"] == source_action["transition_id"]
    )

    service.save_changes(
        draft["id"],
        [
            DraftChangeInput(
                entity_type=ChangeEntityType.TRANSITION,
                operation=ChangeOperation.CREATE,
                draft_entity_id=-1,
                new_value={
                    **{
                        key: value
                        for key, value in source_transition.items()
                        if key != "id"
                    },
                    "position": source_transition["position"] + 1,
                },
            ),
            DraftChangeInput(
                entity_type=ChangeEntityType.TRANSITION_ACTION,
                operation=ChangeOperation.CREATE,
                draft_entity_id=-2,
                new_value={
                    "transition_id": -1,
                    "action_key": source_action["action_key"],
                    "config": source_action["config"],
                    "is_required": source_action["is_required"],
                },
            ),
        ],
    )

    updated = service.get_graph(draft["id"])
    assert any(
        action["transition_id"] == -1
        and action["action_key"] == "required_action"
        for action in updated["transition_actions"]
    )


def test_lists_latest_published_revision_and_marks_stale_drafts(
    session_factory: sessionmaker[Session],
) -> None:
    first_published_id, _ = seed_flow(session_factory)
    service = ChatFlowAdminService(session_factory, AsyncMock())
    stale_draft = service.create_draft(first_published_id)
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        latest = FlowGraphRevisionModel(
            base_revision_id=first_published_id,
            status=RevisionStatus.PUBLISHED,
            version=2,
            created_at=now,
            updated_at=now,
            published_at=now,
        )
        session.add(latest)
        session.flush()
        latest_id = latest.id

    current_draft = service.create_draft(latest_id)

    result = service.list_revisions()

    assert result["published"]["id"] == latest_id
    assert result["published"]["version"] == 2
    drafts = {draft["id"]: draft for draft in result["drafts"]}
    assert drafts[current_draft["id"]]["is_stale"] is False
    assert drafts[stale_draft["id"]]["is_stale"] is True


def test_updates_required_node_message_and_keeps_single_compacted_change(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, message_id = seed_flow(session_factory)
    publisher = AsyncMock()
    service = ChatFlowAdminService(session_factory, publisher)
    draft = service.create_draft(published_id)

    service.save_changes(
        draft["id"],
        [
            DraftChangeInput(
                entity_type=ChangeEntityType.NODE,
                entity_id=message_id,
                operation=ChangeOperation.UPDATE,
                new_value={"message": "Mensagem editada"},
            )
        ],
    )
    result = service.save_changes(
        draft["id"],
        [
            DraftChangeInput(
                entity_type=ChangeEntityType.NODE,
                entity_id=message_id,
                operation=ChangeOperation.UPDATE,
                new_value={
                    "title": "Título editado",
                    "position_x": 420,
                    "position_y": 180,
                },
            )
        ],
    )

    graph = service.get_graph(draft["id"])
    changed = next(item for item in graph["nodes"] if item["id"] == message_id)
    assert result["change_count"] == 1
    assert changed["message"] == "Mensagem editada"
    assert changed["title"] == "Título editado"
    assert changed["position_x"] == 420
    assert changed["position_y"] == 180


def test_can_delete_node_with_required_action_from_draft(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, message_id = seed_flow(session_factory)
    service = ChatFlowAdminService(session_factory, AsyncMock())
    draft = service.create_draft(published_id)
    initial = service.get_graph(draft["id"])
    transition_ids = {
        transition["id"]
        for transition in initial["transitions"]
        if transition["node_id"] == message_id or transition["next_node_id"] == message_id
    }
    action_ids = [
        action["id"]
        for action in initial["transition_actions"]
        if action["transition_id"] in transition_ids
    ]

    service.save_changes(
        draft["id"],
        [
            *[
                DraftChangeInput(
                    entity_type=ChangeEntityType.TRANSITION_ACTION,
                    entity_id=action_id,
                    operation=ChangeOperation.DELETE,
                )
                for action_id in action_ids
            ],
            *[
                DraftChangeInput(
                    entity_type=ChangeEntityType.TRANSITION,
                    entity_id=transition_id,
                    operation=ChangeOperation.DELETE,
                )
                for transition_id in transition_ids
            ],
            DraftChangeInput(
                entity_type=ChangeEntityType.NODE,
                entity_id=message_id,
                operation=ChangeOperation.DELETE,
            )
        ],
    )

    graph = service.get_graph(draft["id"])
    assert all(node["id"] != message_id for node in graph["nodes"])
    assert all(transition["id"] not in transition_ids for transition in graph["transitions"])
    assert all(action["id"] not in action_ids for action in graph["transition_actions"])


@pytest.mark.asyncio
async def test_publishes_diff_and_keeps_change_history(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, message_id = seed_flow(session_factory)
    publisher = AsyncMock()
    service = ChatFlowAdminService(session_factory, publisher)
    draft = service.create_draft(published_id)
    service.save_changes(
        draft["id"],
        [
            DraftChangeInput(
                entity_type=ChangeEntityType.NODE,
                entity_id=message_id,
                operation=ChangeOperation.UPDATE,
                new_value={
                    "message": "Mensagem publicada",
                    "position_x": 640,
                    "position_y": 320,
                },
            )
        ],
    )

    result = await service.publish(draft["id"])

    assert result == {
        "revision_id": draft["id"],
        "version": 2,
        "status": "PUBLISHED",
    }
    publisher.publish.assert_awaited_once()
    with session_factory() as session:
        node_row = session.get(FlowNodeModel, message_id)
        revision = session.get(FlowGraphRevisionModel, draft["id"])
        changes = list(session.scalars(select(FlowGraphChangeModel).where(FlowGraphChangeModel.revision_id == draft["id"])))
    assert node_row is not None and node_row.message == "Mensagem publicada"
    assert (node_row.position_x, node_row.position_y) == (640, 320)
    assert revision is not None and revision.status == RevisionStatus.PUBLISHED
    assert len(changes) == 1


@pytest.mark.asyncio
async def test_can_retry_cache_after_database_publication(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, _ = seed_flow(session_factory)
    publisher = MagicMock()
    publisher.publish = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    service = ChatFlowAdminService(session_factory, publisher)
    draft = service.create_draft(published_id)

    with pytest.raises(FlowCachePublishError) as error:
        await service.publish(draft["id"])

    assert error.value.version == 2
    publisher.publish.side_effect = None
    result = await service.publish(draft["id"])

    assert result["version"] == 2
    assert publisher.publish.await_count == 2
