"""Relational representation of the published chatbot graph."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.db.base import Base
from app.domain.db.delivery_model import JSON_TYPE
from app.domain.enum.chatbot_flow import InputType, NodeType

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
    transition_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.transition.id", ondelete="CASCADE"), nullable=False
    )
    action_key: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FlowInputErrorMessageModel(Base):
    __tablename__ = "input_error_message"
    __table_args__ = {"schema": SCHEMA}

    input_type: Mapped[InputType] = mapped_column(
        Enum(InputType, name="input_type", schema=SCHEMA, create_type=False), primary_key=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)


class FlowRevisionModel(Base):
    """Singleton revision used to publish immutable Redis cache entries."""

    __tablename__ = "revision"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
