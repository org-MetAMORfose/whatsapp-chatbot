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
    ProtectedFlowNodeError,
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


def test_cannot_delete_node_with_required_action(
    session_factory: sessionmaker[Session],
) -> None:
    published_id, message_id = seed_flow(session_factory)
    service = ChatFlowAdminService(session_factory, AsyncMock())
    draft = service.create_draft(published_id)

    with pytest.raises(ProtectedFlowNodeError):
        service.save_changes(
            draft["id"],
            [
                DraftChangeInput(
                    entity_type=ChangeEntityType.NODE,
                    entity_id=message_id,
                    operation=ChangeOperation.DELETE,
                )
            ],
        )


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
