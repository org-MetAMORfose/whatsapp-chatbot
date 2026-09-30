"""Durable Redis cache for the published chatbot graph."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from redis.asyncio import Redis

from app.agent.chat_flow import ChatFlow
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository

logger = logging.getLogger(__name__)

ACTIVE_REVISION_KEY = "chatbot_flow:active_revision"
GRAPH_KEY_PREFIX = "chatbot_flow:graph:"


class FlowProvider(Protocol):
    async def get_flow(self) -> ChatFlow: ...


class StaticFlowProvider:
    """Small provider used by unit tests and explicit in-memory callers."""

    def __init__(self, flow: ChatFlow) -> None:
        self.flow = flow

    async def get_flow(self) -> ChatFlow:
        return self.flow


class ChatFlowCache:
    def __init__(
        self,
        redis_client: Redis[str],
        repository: ChatFlowRepository,
    ) -> None:
        self._redis = redis_client
        self._repository = repository
        self._flow: ChatFlow | None = None
        self._revision: int | None = None
        self._lock = asyncio.Lock()

    async def get_flow(self) -> ChatFlow:
        raw_revision = await self._redis.get(ACTIVE_REVISION_KEY)
        redis_revision = _parse_revision(raw_revision)
        if self._flow is not None and redis_revision == self._revision:
            return self._flow

        async with self._lock:
            raw_revision = await self._redis.get(ACTIVE_REVISION_KEY)
            redis_revision = _parse_revision(raw_revision)
            if self._flow is not None and redis_revision == self._revision:
                return self._flow

            if redis_revision is not None:
                payload = await self._redis.get(f"{GRAPH_KEY_PREFIX}{redis_revision}")
                if payload is not None:
                    try:
                        flow = ChatFlow.from_json(payload)
                    except (ValueError, TypeError):
                        logger.exception(
                            "Invalid chatbot flow cache for revision %s",
                            redis_revision,
                        )
                    else:
                        self._flow = flow
                        self._revision = redis_revision
                        return flow

            revision, flow = await asyncio.to_thread(self._repository.load)
            await self.publish(revision, flow)
            return flow

    async def publish(self, revision: int, flow: ChatFlow) -> None:
        """Write the immutable graph before atomically exposing its revision."""
        graph_key = f"{GRAPH_KEY_PREFIX}{revision}"
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.set(graph_key, flow.model_dump_json())
            pipeline.set(ACTIVE_REVISION_KEY, revision)
            await pipeline.execute()
        self._flow = flow
        self._revision = revision


def _parse_revision(value: str | bytes | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
