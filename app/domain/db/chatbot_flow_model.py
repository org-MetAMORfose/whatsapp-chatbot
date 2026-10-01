"""Relational representation of the published chatbot graph."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.db.base import Base
from app.domain.db.delivery_model import JSON_TYPE
from app.domain.enum.chatbot_flow import (
    ChangeEntityType,
    ChangeOperation,
    InputType,
    NodeType,
    RevisionStatus,
)

SCHEMA = "chatbot_flow"


def utcnow() -> datetime:
    return datetime.now(UTC)


class FlowNodeModel(Base):
    __tablename__ = "node"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[NodeType] = mapped_column(Enum(NodeType, name="node_type", schema=SCHEMA), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    position_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    position_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class FlowTransitionModel(Base):
    __tablename__ = "transition"
    __table_args__ = (
        UniqueConstraint("node_id", "position", name="uq_transition_node_position"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.node.id", ondelete="CASCADE"), nullable=False)
    input_type: Mapped[InputType] = mapped_column(Enum(InputType, name="input_type", schema=SCHEMA), nullable=False)
    expected_value: Mapped[str | None] = mapped_column(String)
    button_label: Mapped[str | None] = mapped_column(String)
    next_node_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.node.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class FlowTransitionActionModel(Base):
    __tablename__ = "transition_action"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transition_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.transition.id", ondelete="CASCADE"), nullable=False)
    action_key: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FlowActionDependencyModel(Base):
    __tablename__ = "action_dependency"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.transition_action.id"), nullable=False)
    depends_on_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.transition_action.id"), nullable=False)


class FlowInputErrorMessageModel(Base):
    __tablename__ = "input_error_message"
    __table_args__ = {"schema": SCHEMA}

    input_type: Mapped[InputType] = mapped_column(Enum(InputType, name="input_type", schema=SCHEMA, create_type=False), primary_key=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)


class FlowGraphRevisionModel(Base):
    """One durable draft or immutable publication of the graph."""

    __tablename__ = "graph_revision"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    base_revision_id: Mapped[int | None] = mapped_column(ForeignKey(f"{SCHEMA}.graph_revision.id"))
    status: Mapped[RevisionStatus] = mapped_column(Enum(RevisionStatus, name="revision_status", schema=SCHEMA), nullable=False)
    version: Mapped[int | None] = mapped_column(Integer, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FlowGraphChangeModel(Base):
    __tablename__ = "graph_change"
    __table_args__ = (
        UniqueConstraint("revision_id", "entity_type", "entity_id", name="uq_graph_change_entity"),
        UniqueConstraint("revision_id", "entity_type", "draft_entity_id", name="uq_graph_change_draft_entity"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.graph_revision.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[ChangeEntityType] = mapped_column(Enum(ChangeEntityType, name="change_entity_type", schema=SCHEMA), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    draft_entity_id: Mapped[int | None] = mapped_column(Integer)
    operation: Mapped[ChangeOperation] = mapped_column(Enum(ChangeOperation, name="change_operation", schema=SCHEMA), nullable=False)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
