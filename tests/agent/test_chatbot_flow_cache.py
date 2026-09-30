from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.agent.chat_flow import ChatFlow, Node
from app.domain.enum.chatbot_flow import NodeType
from app.repository.redis.chatbot_flow_cache import (
    ACTIVE_REVISION_KEY,
    GRAPH_KEY_PREFIX,
    ChatFlowCache,
)


def make_flow(message: str) -> ChatFlow:
    return ChatFlow(
        nodes={
            "start": Node(
                key="start",
                type=NodeType.START,
                title="Início",
                message=message,
                position=0,
            )
        }
    )


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.operations: list[tuple[str, str]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def set(self, key: str, value: object) -> "FakePipeline":
        self.operations.append((key, str(value)))
        return self

    async def execute(self) -> list[bool]:
        for key, value in self.operations:
            self.redis.data[key] = value
        return [True] * len(self.operations)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        assert transaction
        return FakePipeline(self)


@pytest.mark.asyncio
async def test_cache_miss_loads_postgres_and_publishes_without_ttl() -> None:
    redis = FakeRedis()
    repository = MagicMock()
    repository.load.return_value = (4, make_flow("Banco"))
    cache = ChatFlowCache(cast(Any, redis), repository)

    flow = await cache.get_flow()
    repeated = await cache.get_flow()

    start = flow.get("start")
    assert start is not None
    assert start.message == "Banco"
    assert repeated is flow
    repository.load.assert_called_once()
    assert redis.data[ACTIVE_REVISION_KEY] == "4"
    assert f"{GRAPH_KEY_PREFIX}4" in redis.data


@pytest.mark.asyncio
async def test_revision_change_replaces_the_in_memory_graph() -> None:
    redis = FakeRedis()
    repository = MagicMock()
    first = make_flow("Primeira")
    second = make_flow("Segunda")
    repository.load.return_value = (1, first)
    cache = ChatFlowCache(cast(Any, redis), repository)

    initial = (await cache.get_flow()).get("start")
    assert initial is not None
    assert initial.message == "Primeira"
    redis.data[f"{GRAPH_KEY_PREFIX}2"] = second.model_dump_json()
    redis.data[ACTIVE_REVISION_KEY] = "2"

    refreshed = await cache.get_flow()

    refreshed_start = refreshed.get("start")
    assert refreshed_start is not None
    assert refreshed_start.message == "Segunda"
    repository.load.assert_called_once()


@pytest.mark.asyncio
async def test_missing_versioned_payload_recovers_from_postgres() -> None:
    redis = FakeRedis()
    redis.data[ACTIVE_REVISION_KEY] = "99"
    repository = MagicMock()
    repository.load.return_value = (3, make_flow("Recuperado"))
    cache = ChatFlowCache(cast(Any, redis), repository)

    flow = await cache.get_flow()

    start = flow.get("start")
    assert start is not None
    assert start.message == "Recuperado"
    assert redis.data[ACTIVE_REVISION_KEY] == "3"
