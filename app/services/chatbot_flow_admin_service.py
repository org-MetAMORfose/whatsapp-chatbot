"""Durable chatbot graph drafts, validation and transactional publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agent.action_catalog import MANAGED_ACTION_KEYS, validate_managed_action_config
from app.agent.chat_flow import ChatFlow, Node, Transition, TransitionAction
from app.domain.db.chatbot_flow_model import (
    FlowActionDependencyModel,
    FlowGraphChangeModel,
    FlowGraphRevisionModel,
    FlowInputErrorMessageModel,
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
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.services.chatbot_flow_validation_service import (
    ChatFlowValidator,
    FlowValidationResult,
)


def _now() -> datetime:
    return datetime.now(UTC)


class FlowPublisher(Protocol):
    async def publish(self, revision: int, flow: ChatFlow) -> None: ...


class FlowDraftError(Exception):
    pass


class FlowDraftNotFoundError(FlowDraftError):
    pass


class FlowDraftConflictError(FlowDraftError):
    pass


class InvalidFlowChangeError(FlowDraftError):
    pass


class ProtectedFlowNodeError(InvalidFlowChangeError):
    def __init__(self, node_id: int, node_key: str) -> None:
        super().__init__("Um nó com action obrigatória não pode ser apagado.")
        self.node_id = node_id
        self.node_key = node_key


class InvalidFlowDraftError(FlowDraftError):
    def __init__(self, result: FlowValidationResult) -> None:
        super().__init__("O draft do fluxo é inválido.")
        self.result = result


class FlowCachePublishError(FlowDraftError):
    def __init__(self, revision_id: int, version: int) -> None:
        super().__init__("O fluxo foi publicado no PostgreSQL, mas a atualização do cache falhou. Repita a publicação desta revisão.")
        self.revision_id = revision_id
        self.version = version


@dataclass(frozen=True)
class DraftChangeInput:
    entity_type: ChangeEntityType
    operation: ChangeOperation
    entity_id: int | None = None
    draft_entity_id: int | None = None
    new_value: dict[str, Any] | None = None


COLLECTION_BY_ENTITY = {
    ChangeEntityType.NODE: "nodes",
    ChangeEntityType.TRANSITION: "transitions",
    ChangeEntityType.TRANSITION_ACTION: "transition_actions",
    ChangeEntityType.INPUT_ERROR_MESSAGE: "input_error_messages",
}


class ChatFlowAdminService:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        publisher: FlowPublisher,
        validator: ChatFlowValidator | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._publisher = publisher
        self._validator = validator or ChatFlowValidator()
        self._repository = ChatFlowRepository(session_factory)

    def create_draft(self, base_revision_id: int | None = None) -> dict[str, Any]:
        with self._session_factory() as session, session.begin():
            published = self._latest_published(session)
            if published is None:
                raise FlowDraftConflictError("Não existe uma revisão publicada.")
            if base_revision_id is not None and published.id != base_revision_id:
                raise FlowDraftConflictError("A revisão-base não é mais a revisão publicada.")
            now = _now()
            revision = FlowGraphRevisionModel(
                base_revision_id=published.id,
                status=RevisionStatus.DRAFT,
                version=None,
                created_at=now,
                updated_at=now,
            )
            session.add(revision)
            session.flush()
            return self._revision_payload(revision)

    def list_revisions(self) -> dict[str, Any]:
        with self._session_factory() as session:
            published = self._latest_published(session)
            published_id = published.id if published is not None else None
            drafts = list(
                session.scalars(
                    select(FlowGraphRevisionModel)
                    .where(FlowGraphRevisionModel.status == RevisionStatus.DRAFT)
                    .order_by(FlowGraphRevisionModel.updated_at.desc(), FlowGraphRevisionModel.id.desc())
                )
            )
            return {
                "published": self._revision_payload(published) if published is not None else None,
                "drafts": [{**self._revision_payload(draft), "is_stale": draft.base_revision_id != published_id} for draft in drafts],
            }

    def get_graph(self, revision_id: int) -> dict[str, Any]:
        with self._session_factory() as session:
            revision = self._revision(session, revision_id)
            snapshot = self._snapshot(session)
            if revision.status == RevisionStatus.DRAFT:
                self._assert_current_base(session, revision)
                snapshot = self._apply_changes(
                    snapshot,
                    list(
                        session.scalars(
                            select(FlowGraphChangeModel).where(FlowGraphChangeModel.revision_id == revision.id).order_by(FlowGraphChangeModel.id)
                        )
                    ),
                )
            snapshot["revision"] = self._revision_payload(revision)
            return snapshot

    def save_changes(
        self,
        revision_id: int,
        changes: list[DraftChangeInput],
    ) -> dict[str, Any]:
        with self._session_factory() as session, session.begin():
            revision = self._draft(session, revision_id, lock=True)
            self._assert_current_base(session, revision)
            base = self._snapshot(session)
            current = self._apply_changes(base, self._changes(session, revision.id))
            for change in changes:
                self._save_change(session, revision, current, change)
                session.flush()
                current = self._apply_changes(base, self._changes(session, revision.id))
            revision.updated_at = _now()
            session.flush()
            count = session.scalar(select(func.count(FlowGraphChangeModel.id)).where(FlowGraphChangeModel.revision_id == revision.id))
            return {"revision_id": revision.id, "change_count": int(count or 0)}

    def validate(self, revision_id: int) -> FlowValidationResult:
        with self._session_factory() as session:
            revision = self._revision(session, revision_id)
            snapshot = self._snapshot(session)
            changes: list[FlowGraphChangeModel] = []
            if revision.status == RevisionStatus.DRAFT:
                self._assert_current_base(session, revision)
                changes = self._changes(session, revision.id)
                snapshot = self._apply_changes(snapshot, changes)
            flow = self._flow_from_snapshot(snapshot)
            deleted_required = self._deleted_required_nodes(session, changes)
            return self._validator.validate(
                flow,
                deleted_required_nodes=deleted_required,
            )

    async def publish(self, revision_id: int) -> dict[str, Any]:
        with self._session_factory() as session, session.begin():
            revision = self._revision_for_update(session, revision_id)
            if revision.status == RevisionStatus.PUBLISHED:
                published = self._latest_published(session)
                if published is None or published.id != revision.id or revision.version is None:
                    raise FlowDraftConflictError("Somente a revisão publicada atual pode ter o cache republicado.")
                published_version = revision.version
            elif revision.status != RevisionStatus.DRAFT:
                raise FlowDraftConflictError("A revisão não está mais em edição.")
            else:
                self._latest_published(session, lock=True)
                published = self._latest_published(session)
                if published is None or revision.base_revision_id != published.id:
                    raise FlowDraftConflictError("Outra revisão foi publicada depois da criação deste draft.")
                changes = self._changes(session, revision.id)
                snapshot = self._apply_changes(self._snapshot(session), changes)
                result = self._validator.validate(
                    self._flow_from_snapshot(snapshot),
                    deleted_required_nodes=self._deleted_required_nodes(session, changes),
                )
                if not result.valid:
                    raise InvalidFlowDraftError(result)
                self._apply_publication(session, changes)
                published_version = (published.version or 0) + 1
                now = _now()
                revision.status = RevisionStatus.PUBLISHED
                revision.version = published_version
                revision.updated_at = now
                revision.published_at = now

        loaded_version, flow = self._repository.load()
        if loaded_version != published_version:
            raise FlowDraftConflictError("Uma revisão mais nova foi publicada antes da atualização do cache.")
        try:
            await self._publisher.publish(loaded_version, flow)
        except Exception as exc:
            raise FlowCachePublishError(revision_id, loaded_version) from exc
        return {
            "revision_id": revision_id,
            "version": loaded_version,
            "status": RevisionStatus.PUBLISHED.value,
        }

    def discard(self, revision_id: int) -> dict[str, Any]:
        with self._session_factory() as session, session.begin():
            revision = self._draft(session, revision_id, lock=True)
            revision.status = RevisionStatus.DISCARDED
            revision.updated_at = _now()
            return self._revision_payload(revision)

    def _save_change(
        self,
        session: Session,
        revision: FlowGraphRevisionModel,
        current_snapshot: dict[str, Any],
        change: DraftChangeInput,
    ) -> None:
        self._validate_change_identity(change)
        current = self._find_entity(
            current_snapshot,
            change.entity_type,
            change.entity_id if change.entity_id is not None else change.draft_entity_id,
        )
        existing = session.scalar(
            select(FlowGraphChangeModel).where(
                FlowGraphChangeModel.revision_id == revision.id,
                FlowGraphChangeModel.entity_type == change.entity_type,
                (
                    FlowGraphChangeModel.entity_id == change.entity_id
                    if change.entity_id is not None
                    else FlowGraphChangeModel.draft_entity_id == change.draft_entity_id
                ),
            )
        )
        if current is None and existing is not None and existing.operation == ChangeOperation.DELETE and change.operation == ChangeOperation.UPDATE:
            current = dict(existing.previous_value or {})

        if change.operation == ChangeOperation.CREATE:
            if change.new_value is None:
                raise InvalidFlowChangeError("CREATE exige new_value.")
            if current is not None and existing is None:
                raise InvalidFlowChangeError("CREATE usa um draft_entity_id já existente.")
            desired = {**change.new_value, "id": change.draft_entity_id}
            previous = None
            if change.entity_type == ChangeEntityType.TRANSITION_ACTION:
                self._validate_managed_action(desired)
        elif change.operation == ChangeOperation.UPDATE:
            if current is None or change.new_value is None:
                raise InvalidFlowChangeError("UPDATE exige uma entidade existente e new_value.")
            previous = dict(existing.previous_value) if existing is not None and existing.previous_value is not None else dict(current)
            target_id = change.entity_id if change.entity_id is not None else change.draft_entity_id
            desired = {**current, **change.new_value, "id": target_id}
            if change.entity_type == ChangeEntityType.TRANSITION_ACTION:
                self._validate_managed_action(desired)
            if desired == previous and (existing is None or existing.operation != ChangeOperation.CREATE):
                if existing is not None:
                    session.delete(existing)
                return
        else:
            if current is None:
                raise InvalidFlowChangeError("DELETE exige uma entidade existente.")
            if change.entity_type == ChangeEntityType.NODE:
                node_key = str(current["key"])
                if self._node_has_required_action(session, int(current["id"])):
                    raise ProtectedFlowNodeError(int(current["id"]), node_key)
            if change.entity_type == ChangeEntityType.TRANSITION_ACTION:
                self._validate_managed_action(current)
                self._assert_action_can_be_deleted(session, int(current["id"]))
            previous = dict(current)
            desired = None
            if existing is not None and existing.operation == ChangeOperation.CREATE:
                session.delete(existing)
                return

        if existing is None:
            existing = FlowGraphChangeModel(
                revision_id=revision.id,
                entity_type=change.entity_type,
                entity_id=change.entity_id,
                draft_entity_id=change.draft_entity_id,
                operation=change.operation,
                previous_value=previous,
                new_value=desired,
                created_at=_now(),
            )
            session.add(existing)
        else:
            if existing.operation != ChangeOperation.CREATE:
                existing.operation = change.operation
            existing.new_value = desired

    @staticmethod
    def _validate_managed_action(value: dict[str, Any]) -> None:
        action_key = value.get("action_key")
        if action_key not in MANAGED_ACTION_KEYS:
            raise InvalidFlowChangeError("Somente as actions anunciadas em /chatbot-flow/actions podem ser adicionadas, alteradas ou removidas.")
        try:
            validate_managed_action_config(str(action_key), value.get("config"))
        except (ValidationError, ValueError) as exc:
            raise InvalidFlowChangeError(f"Config inválido para a action {action_key}.") from exc

    @staticmethod
    def _validate_change_identity(change: DraftChangeInput) -> None:
        if change.operation == ChangeOperation.CREATE:
            if change.entity_id is not None or change.draft_entity_id is None:
                raise InvalidFlowChangeError("CREATE exige somente draft_entity_id.")
            if change.draft_entity_id >= 0:
                raise InvalidFlowChangeError("draft_entity_id deve ser negativo.")
        elif (change.entity_id is None) == (change.draft_entity_id is None):
            raise InvalidFlowChangeError("UPDATE e DELETE exigem exatamente um entity_id ou draft_entity_id.")
        elif change.draft_entity_id is not None and change.draft_entity_id >= 0:
            raise InvalidFlowChangeError("draft_entity_id deve ser negativo.")

    @staticmethod
    def _changes(session: Session, revision_id: int) -> list[FlowGraphChangeModel]:
        return list(
            session.scalars(select(FlowGraphChangeModel).where(FlowGraphChangeModel.revision_id == revision_id).order_by(FlowGraphChangeModel.id))
        )

    @staticmethod
    def _revision_payload(revision: FlowGraphRevisionModel) -> dict[str, Any]:
        return {
            "id": revision.id,
            "base_revision_id": revision.base_revision_id,
            "status": revision.status.value,
            "version": revision.version,
            "created_at": revision.created_at,
            "updated_at": revision.updated_at,
            "published_at": revision.published_at,
        }

    @staticmethod
    def _latest_published(
        session: Session,
        *,
        lock: bool = False,
    ) -> FlowGraphRevisionModel | None:
        statement = (
            select(FlowGraphRevisionModel)
            .where(FlowGraphRevisionModel.status == RevisionStatus.PUBLISHED)
            .order_by(FlowGraphRevisionModel.version.desc())
            .limit(1)
        )
        if lock:
            statement = statement.with_for_update()
        return session.scalar(statement)

    @staticmethod
    def _revision(session: Session, revision_id: int) -> FlowGraphRevisionModel:
        revision = session.get(FlowGraphRevisionModel, revision_id)
        if revision is None:
            raise FlowDraftNotFoundError(f"Revisão {revision_id} não encontrada.")
        return revision

    @staticmethod
    def _revision_for_update(
        session: Session,
        revision_id: int,
    ) -> FlowGraphRevisionModel:
        revision = session.scalar(select(FlowGraphRevisionModel).where(FlowGraphRevisionModel.id == revision_id).with_for_update())
        if revision is None:
            raise FlowDraftNotFoundError(f"Revisão {revision_id} não encontrada.")
        return revision

    def _draft(
        self,
        session: Session,
        revision_id: int,
        *,
        lock: bool,
    ) -> FlowGraphRevisionModel:
        statement = select(FlowGraphRevisionModel).where(FlowGraphRevisionModel.id == revision_id)
        if lock:
            statement = statement.with_for_update()
        revision = session.scalar(statement)
        if revision is None:
            raise FlowDraftNotFoundError(f"Revisão {revision_id} não encontrada.")
        if revision.status != RevisionStatus.DRAFT:
            raise FlowDraftConflictError("A revisão não está mais em edição.")
        return revision

    def _assert_current_base(
        self,
        session: Session,
        revision: FlowGraphRevisionModel,
    ) -> None:
        published = self._latest_published(session)
        if published is None or revision.base_revision_id != published.id:
            raise FlowDraftConflictError("O draft está baseado em uma revisão que não é mais a atual.")

    @staticmethod
    def _snapshot(session: Session) -> dict[str, Any]:
        nodes = [
            {
                "id": row.id,
                "key": row.key,
                "type": row.type.value,
                "title": row.title,
                "description": row.description,
                "message": row.message,
                "position": row.position,
                "position_x": row.position_x,
                "position_y": row.position_y,
            }
            for row in session.scalars(select(FlowNodeModel).order_by(FlowNodeModel.position, FlowNodeModel.id))
        ]
        transitions = [
            {
                "id": row.id,
                "node_id": row.node_id,
                "input_type": row.input_type.value,
                "expected_value": row.expected_value,
                "button_label": row.button_label,
                "next_node_id": row.next_node_id,
                "position": row.position,
            }
            for row in session.scalars(
                select(FlowTransitionModel).order_by(
                    FlowTransitionModel.node_id,
                    FlowTransitionModel.position,
                    FlowTransitionModel.id,
                )
            )
        ]
        actions = [
            {
                "id": row.id,
                "transition_id": row.transition_id,
                "action_key": row.action_key,
                "config": row.config,
                "is_required": row.is_required,
            }
            for row in session.scalars(
                select(FlowTransitionActionModel).order_by(
                    FlowTransitionActionModel.transition_id,
                    FlowTransitionActionModel.id,
                )
            )
        ]
        error_ids = {input_type: index for index, input_type in enumerate(InputType, 1)}
        errors = [
            {
                "id": error_ids[InputType(row.input_type)],
                "input_type": row.input_type.value,
                "message": row.message,
            }
            for row in session.scalars(select(FlowInputErrorMessageModel))
        ]
        dependencies = [
            {
                "id": row.id,
                "action_id": row.action_id,
                "depends_on_id": row.depends_on_id,
            }
            for row in session.scalars(select(FlowActionDependencyModel))
        ]
        return {
            "nodes": nodes,
            "transitions": transitions,
            "transition_actions": actions,
            "input_error_messages": errors,
            "action_dependencies": dependencies,
        }

    @staticmethod
    def _apply_changes(
        snapshot: dict[str, Any],
        changes: list[FlowGraphChangeModel],
    ) -> dict[str, Any]:
        materialized = {key: [dict(item) for item in value] if isinstance(value, list) else value for key, value in snapshot.items()}
        for change in changes:
            collection_name = COLLECTION_BY_ENTITY[ChangeEntityType(change.entity_type)]
            collection = materialized[collection_name]
            target_id = change.draft_entity_id if change.operation == ChangeOperation.CREATE else change.entity_id
            index = next(
                (index for index, item in enumerate(collection) if item.get("id") == target_id),
                None,
            )
            if change.operation == ChangeOperation.DELETE:
                if index is not None:
                    collection.pop(index)
                continue
            value = dict(change.new_value or {})
            value["id"] = target_id
            if index is None:
                collection.append(value)
            else:
                collection[index] = value
        return materialized

    @staticmethod
    def _find_entity(
        snapshot: dict[str, Any],
        entity_type: ChangeEntityType,
        entity_id: int | None,
    ) -> dict[str, Any] | None:
        if entity_id is None:
            return None
        return next(
            (item for item in snapshot[COLLECTION_BY_ENTITY[entity_type]] if item["id"] == entity_id),
            None,
        )

    @staticmethod
    def _flow_from_snapshot(snapshot: dict[str, Any]) -> ChatFlow:
        node_keys = {row["id"]: row["key"] for row in snapshot["nodes"]}
        dependencies: dict[int, list[int]] = {}
        for row in snapshot["action_dependencies"]:
            dependencies.setdefault(row["action_id"], []).append(row["depends_on_id"])
        actions: dict[int, list[TransitionAction]] = {}
        for row in snapshot["transition_actions"]:
            actions.setdefault(row["transition_id"], []).append(
                TransitionAction(
                    id=row["id"],
                    action_key=row["action_key"],
                    config=row.get("config"),
                    is_required=row["is_required"],
                    depends_on_ids=dependencies.get(row["id"], []),
                )
            )
        transitions: dict[int, list[Transition]] = {}
        for row in snapshot["transitions"]:
            target = node_keys.get(row["next_node_id"], f"__missing_{row['next_node_id']}")
            transitions.setdefault(row["node_id"], []).append(
                Transition(
                    id=row["id"],
                    input_type=InputType(row["input_type"]),
                    expected_value=row.get("expected_value"),
                    button_label=row.get("button_label"),
                    target=target,
                    position=row["position"],
                    actions=actions.get(row["id"], []),
                )
            )
        nodes = {
            row["key"]: Node(
                id=row["id"],
                key=row["key"],
                type=NodeType(row["type"]),
                title=row["title"],
                description=row.get("description"),
                message=row["message"],
                position=row["position"],
                position_x=row.get("position_x", 0),
                position_y=row.get("position_y", 0),
                transitions=transitions.get(row["id"], []),
            )
            for row in snapshot["nodes"]
        }
        input_errors = {InputType(row["input_type"]): row["message"] for row in snapshot["input_error_messages"]}
        return ChatFlow.model_construct(
            nodes=nodes,
            input_error_messages=input_errors,
        )

    @staticmethod
    def _node_has_required_action(session: Session, node_id: int) -> bool:
        return bool(
            session.scalar(
                select(FlowTransitionActionModel.id)
                .join(
                    FlowTransitionModel,
                    FlowTransitionModel.id == FlowTransitionActionModel.transition_id,
                )
                .where(
                    FlowTransitionModel.node_id == node_id,
                    FlowTransitionActionModel.is_required.is_(True),
                )
                .limit(1)
            )
        )

    @staticmethod
    def _assert_action_can_be_deleted(session: Session, action_id: int) -> None:
        dependency = session.scalar(
            select(FlowActionDependencyModel.id)
            .where(
                or_(
                    FlowActionDependencyModel.action_id == action_id,
                    FlowActionDependencyModel.depends_on_id == action_id,
                )
            )
            .limit(1)
        )
        if dependency is not None:
            raise InvalidFlowChangeError("Uma action usada por uma dependência fixa não pode ser apagada.")

    def _deleted_required_nodes(
        self,
        session: Session,
        changes: list[FlowGraphChangeModel],
    ) -> list[tuple[int, str]]:
        deleted: list[tuple[int, str]] = []
        for change in changes:
            if (
                change.entity_type == ChangeEntityType.NODE
                and change.operation == ChangeOperation.DELETE
                and change.entity_id is not None
                and self._node_has_required_action(session, change.entity_id)
            ):
                previous = change.previous_value or {}
                deleted.append((change.entity_id, str(previous.get("key", ""))))
        return deleted

    def _apply_publication(
        self,
        session: Session,
        changes: list[FlowGraphChangeModel],
    ) -> None:
        creates = [change for change in changes if change.operation == ChangeOperation.CREATE]
        updates = [change for change in changes if change.operation == ChangeOperation.UPDATE]
        deletes = [change for change in changes if change.operation == ChangeOperation.DELETE]
        id_maps: dict[ChangeEntityType, dict[int, int]] = {entity_type: {} for entity_type in ChangeEntityType}
        order = (
            ChangeEntityType.NODE,
            ChangeEntityType.TRANSITION,
            ChangeEntityType.TRANSITION_ACTION,
            ChangeEntityType.INPUT_ERROR_MESSAGE,
        )
        for entity_type in order:
            for change in creates:
                if change.entity_type == entity_type:
                    self._create_entity(session, change, id_maps)
        for change in updates:
            self._update_entity(session, change, id_maps)
        for entity_type in reversed(order):
            for change in deletes:
                if change.entity_type == entity_type:
                    self._delete_entity(session, change)

    @staticmethod
    def _resolve_id(
        value: int,
        entity_type: ChangeEntityType,
        id_maps: dict[ChangeEntityType, dict[int, int]],
    ) -> int:
        if value >= 0:
            return value
        try:
            return id_maps[entity_type][value]
        except KeyError as exc:
            raise InvalidFlowChangeError(f"Referência temporária não encontrada: {value}") from exc

    def _create_entity(
        self,
        session: Session,
        change: FlowGraphChangeModel,
        id_maps: dict[ChangeEntityType, dict[int, int]],
    ) -> None:
        value = dict(change.new_value or {})
        value.pop("id", None)
        if change.entity_type == ChangeEntityType.NODE:
            model: Any = FlowNodeModel(**value)
        elif change.entity_type == ChangeEntityType.TRANSITION:
            value["node_id"] = self._resolve_id(value["node_id"], ChangeEntityType.NODE, id_maps)
            value["next_node_id"] = self._resolve_id(value["next_node_id"], ChangeEntityType.NODE, id_maps)
            model = FlowTransitionModel(**value)
        elif change.entity_type == ChangeEntityType.TRANSITION_ACTION:
            value["transition_id"] = self._resolve_id(value["transition_id"], ChangeEntityType.TRANSITION, id_maps)
            model = FlowTransitionActionModel(**value)
        else:
            value.pop("id", None)
            model = FlowInputErrorMessageModel(**value)
        session.add(model)
        session.flush()
        if change.draft_entity_id is not None and hasattr(model, "id"):
            id_maps[ChangeEntityType(change.entity_type)][change.draft_entity_id] = model.id

    def _update_entity(
        self,
        session: Session,
        change: FlowGraphChangeModel,
        id_maps: dict[ChangeEntityType, dict[int, int]],
    ) -> None:
        value = dict(change.new_value or {})
        value.pop("id", None)
        if change.entity_type == ChangeEntityType.INPUT_ERROR_MESSAGE:
            previous = change.previous_value or {}
            model: Any = session.get(
                FlowInputErrorMessageModel,
                InputType(previous["input_type"]),
            )
        else:
            model_class = {
                ChangeEntityType.NODE: FlowNodeModel,
                ChangeEntityType.TRANSITION: FlowTransitionModel,
                ChangeEntityType.TRANSITION_ACTION: FlowTransitionActionModel,
            }[ChangeEntityType(change.entity_type)]
            model = session.get(model_class, change.entity_id)
        if model is None:
            raise InvalidFlowChangeError("A entidade atualizada não existe.")
        if change.entity_type == ChangeEntityType.TRANSITION:
            value["node_id"] = self._resolve_id(value["node_id"], ChangeEntityType.NODE, id_maps)
            value["next_node_id"] = self._resolve_id(value["next_node_id"], ChangeEntityType.NODE, id_maps)
        if change.entity_type == ChangeEntityType.TRANSITION_ACTION:
            value["transition_id"] = self._resolve_id(value["transition_id"], ChangeEntityType.TRANSITION, id_maps)
        for key, item in value.items():
            setattr(model, key, item)

    @staticmethod
    def _delete_entity(session: Session, change: FlowGraphChangeModel) -> None:
        model: Any
        if change.entity_type == ChangeEntityType.INPUT_ERROR_MESSAGE:
            previous = change.previous_value or {}
            model = session.get(
                FlowInputErrorMessageModel,
                InputType(previous["input_type"]),
            )
        else:
            model_class = {
                ChangeEntityType.NODE: FlowNodeModel,
                ChangeEntityType.TRANSITION: FlowTransitionModel,
                ChangeEntityType.TRANSITION_ACTION: FlowTransitionActionModel,
            }[ChangeEntityType(change.entity_type)]
            model = session.get(model_class, change.entity_id)
        if model is None:
            raise InvalidFlowChangeError("A entidade removida não existe.")
        session.delete(model)
