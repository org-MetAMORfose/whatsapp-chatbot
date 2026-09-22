from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from app.agent.agent import Response
from app.context import AppContext
from app.domain.db.delivery_model import InboxModel, OutboxModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.message_queue.message_queue import MessageQueue
from app.repository.redis.staged_state import StagedState, stage_state
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.transaction import transaction
from app.services.dispatcher_service import MessageDispatcherService
from app.services.inbound_processor import InboundProcessor


def message() -> Message:
    return Message(event_id=uuid4().hex, message_id=1, channel=Channel.WHATSAPP,
                   chat_id=uuid4().hex, user_id=uuid4().hex, created_at=None, content="hello")


@pytest.mark.asyncio
async def test_claim_survives_consumer_crash_and_deduplicates_publish(redis_client):
    queue = MessageQueue(redis_client, uuid4().hex)
    msg = message()
    await queue.publish(msg)
    await queue.publish(msg)
    claimed = await queue.claim_next()
    assert claimed is not None
    restarted = MessageQueue(redis_client, queue.queue_name)
    recovered = await restarted.claim_next()
    assert recovered is not None and recovered.id == claimed.id and recovered.attempts == 2
    await restarted.ack(recovered)
    assert await redis_client.xlen(queue.key) == 0
    assert (await redis_client.xpending(queue.key, queue.group))["pending"] == 0


@pytest.mark.asyncio
async def test_committed_result_replays_without_repeating_actions(factory, redis_client):
    inbound, outbound = MessageQueue(redis_client, uuid4().hex), MessageQueue(redis_client, uuid4().hex)
    msg = message()
    state_key = "test:state:" + uuid4().hex
    state = StagedState(redis_client)
    outbox = OutboxRepository(factory)
    agent = MagicMock()

    async def process(_):
        await state.set(state_key, "next-state", ex=100)
        outbox.enqueue(str(msg.event_id), "email.send.v1", {"to": "test@example.invalid"})
        return Response(content="done")

    agent._process_message = AsyncMock(side_effect=process)
    processor = InboundProcessor(factory, agent, PersonRepository(factory), inbound, outbound, None)
    await inbound.publish(msg)
    delivery = await inbound.claim_next()
    assert delivery is not None
    complete = inbound.complete_inbound
    inbound.complete_inbound = AsyncMock(side_effect=ConnectionError("Redis temporarily unavailable"))  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await processor.process(delivery)
    assert await redis_client.get(state_key) is None
    with factory() as session:
        assert session.get(InboxModel, msg.event_id) is not None
        assert session.get(OutboxModel, msg.event_id) is not None
    inbound.complete_inbound = complete  # type: ignore[method-assign]
    recovered = await inbound.claim_next()
    assert recovered is not None
    await processor.process(recovered)
    agent._process_message.assert_awaited_once()
    assert await redis_client.get(state_key) == "next-state"
    assert await redis_client.xlen(outbound.key) == 1
    # A delayed duplicate must not restore the earlier state or enqueue another reply.
    await redis_client.set(state_key, "newer-state")
    await redis_client.xadd(inbound.key, {"payload": msg.model_dump_json()})
    duplicate = await inbound.claim_next()
    assert duplicate is not None
    await processor.process(duplicate)
    assert await redis_client.get(state_key) == "newer-state"
    assert await redis_client.xlen(outbound.key) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1


@pytest.mark.asyncio
async def test_failure_rolls_back_business_outbox_and_state(factory, redis_client):
    repo = PersonRepository(factory)
    outbox = OutboxRepository(factory)
    state = StagedState(redis_client)
    key = "test:state:" + uuid4().hex
    with pytest.raises(RuntimeError), stage_state(), transaction(factory):
        repo.get_or_create_person("123", Channel.WHATSAPP)
        outbox.enqueue("operation", "email.send.v1", {})
        await state.set(key, "uncommitted", ex=60)
        assert await state.get(key) == "uncommitted"
        raise RuntimeError("failed action")
    assert await redis_client.get(key) is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PersonModel)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxModel)) == 0


def test_outbox_scheduling_recovery_and_stale_completion(factory):
    repo = OutboxRepository(factory)
    with transaction(factory):
        repo.enqueue("future", "email.send.v1", {}, datetime.now(UTC) + timedelta(days=1))
        repo.enqueue("now", "sheets.patient.upsert.v1", {})
    item = repo.claim()
    assert item is not None
    assert item.id == "now" and item.attempts == 1
    assert repo.claim() is None
    with factory() as session, session.begin():
        session.execute(update(OutboxModel).where(OutboxModel.id == "now").values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
    recovered = repo.claim()
    assert recovered is not None
    assert recovered.id == item.id and recovered.attempts == 2
    repo.finish(item)
    with factory() as session:
        assert session.get(OutboxModel, "now").status == "processing"
    repo.finish(recovered, TimeoutError())
    with factory() as session:
        row = session.get(OutboxModel, "now")
        assert row.status == "pending" and row.last_error == "TimeoutError"
    assert repo.claim() is None


@pytest.mark.asyncio
async def test_outbound_receipt_prevents_duplicate_send_and_history(factory):
    dispatcher = MessageDispatcherService(AppContext(), MagicMock(), PersonRepository(factory))
    adapter = MagicMock(send_message=AsyncMock())
    dispatcher.register_adapter(Channel.WHATSAPP, adapter)
    msg = message()
    await dispatcher.dispatch(msg)
    await dispatcher.dispatch(msg)
    adapter.send_message.assert_awaited_once()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1


@pytest.mark.asyncio
async def test_poison_message_moves_to_failed_stream(redis_client):
    queue = MessageQueue(redis_client, uuid4().hex)
    await redis_client.xadd(queue.key, {"payload": "invalid json"})
    delivery = await queue.claim_next()
    assert delivery is not None
    with pytest.raises(ValueError):
        _ = delivery.message
    await queue.dead_letter(delivery, ValueError())
    assert (await queue.get_metrics()) == {"pending": 0, "failed": 1}


@pytest.mark.asyncio
async def test_legacy_queue_migration_is_fifo_and_keeps_history(redis_client):
    from app.migrate_queues import MOVE
    name = uuid4().hex
    legacy, stream = f"test:legacy:{name}", f"test:stream:{name}"
    first, second = message(), message()
    first.history_id = 77
    await redis_client.lpush(legacy, first.model_dump_json())
    await redis_client.lpush(legacy, second.model_dump_json())
    assert await redis_client.eval(MOVE, 2, legacy, stream, "legacy:one") == 1
    assert await redis_client.eval(MOVE, 2, legacy, stream, "legacy:two") == 1
    assert await redis_client.eval(MOVE, 2, legacy, stream, "legacy:three") == 0
    rows = await redis_client.xrange(stream)
    assert Message.model_validate_json(rows[0][1]["payload"]).history_id == 77
    assert Message.model_validate_json(rows[1][1]["payload"]).chat_id == second.chat_id
    await redis_client.delete(legacy, stream)
