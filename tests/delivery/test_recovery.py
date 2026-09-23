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
from app.infra.message_queue import MessageQueue
from app.repository.redis.staged_state import StagedState, stage_state
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.transaction import transaction
from app.services.dispatcher_service import MessageDispatcherService
from app.services.inbound_processor import InboundProcessor


def message() -> Message:
    return Message(event_id=uuid4().hex, message_id=1, channel=Channel.WHATSAPP,
                   chat_id=uuid4().hex, user_id=uuid4().hex, created_at=datetime.now(UTC), content="hello")


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
    assert (await queue.get_metrics())["pending"] == 0


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
    await inbound.retry(delivery, 0)
    recovered = await inbound.claim_next()
    assert recovered is not None
    await processor.process(recovered)
    agent._process_message.assert_awaited_once()
    assert await redis_client.get(state_key) == "next-state"
    assert (await outbound.get_metrics())["pending"] == 1
    # A delayed duplicate must not restore the earlier state or enqueue another reply.
    await redis_client.set(state_key, "newer-state")
    # Publisher suppresses the completed duplicate while its bounded receipt exists.
    await inbound.publish(msg)
    assert await inbound.claim_next() is None
    assert await redis_client.get(state_key) == "newer-state"
    assert (await outbound.get_metrics())["pending"] == 1
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
async def test_chat_order_and_retry_does_not_block_other_chats(redis_client):
    queue = MessageQueue(redis_client, uuid4().hex)
    now = datetime.now(UTC)
    a_old = message().model_copy(update={"chat_id": "a", "created_at": now - timedelta(seconds=20)})
    a_new = message().model_copy(update={"chat_id": "a", "created_at": now - timedelta(seconds=10)})
    b = message().model_copy(update={"chat_id": "b", "created_at": now - timedelta(seconds=5)})
    for msg in (a_new, b, a_old):
        await queue.publish(msg)
    first = await queue.claim_next()
    assert first is not None and first.message.event_id == a_old.event_id
    await queue.retry(first, 60)
    other = await queue.claim_next()
    assert other is not None and other.message.chat_id == "b"
    await queue.ack(other)
    assert await queue.claim_next() is None
    await queue.retry(first, 0)
    again = await queue.claim_next()
    assert again is not None and again.id == first.id
    await queue.ack(again)
    last = await queue.claim_next()
    assert last is not None and last.message.event_id == a_new.event_id


@pytest.mark.asyncio
async def test_expired_ingress_archived_but_not_queued(factory, redis_client):
    from app.services.receiver_service import MessageReceiverService
    queue = MessageQueue(redis_client, uuid4().hex)
    receiver = MessageReceiverService(queue, PersonRepository(factory))
    old = message().model_copy(update={"created_at": datetime.now(UTC) - timedelta(minutes=6)})
    await receiver.handle(old)
    await receiver.handle(old)
    assert await queue.claim_next() is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1


@pytest.mark.asyncio
async def test_queued_message_expires_but_history_remains(factory, redis_client):
    import time
    from unittest.mock import patch

    from app.services.receiver_service import MessageReceiverService
    queue = MessageQueue(redis_client, uuid4().hex)
    receiver = MessageReceiverService(queue, PersonRepository(factory))
    await receiver.handle(message())
    with patch("app.infra.message_queue.time.time", return_value=time.time() + 301):
        assert await queue.claim_next() is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1


@pytest.mark.asyncio
async def test_queue_capacity_and_ttl(redis_client):
    from app.infra.message_queue import QueueFullError
    queue = MessageQueue(redis_client, uuid4().hex)
    queue.max_records = 2
    await queue.publish(message())
    await queue.publish(message())
    with pytest.raises(QueueFullError):
        await queue.publish(message())
    assert (await queue.get_metrics())["pending"] == 2
    for key in queue.keys[:2]:
        assert 0 < await redis_client.ttl(key) <= 3600


@pytest.mark.asyncio
async def test_state_record_cap_and_ttl(redis_client):
    from app.infra.redis_policy import STATE_INDEX
    state = StagedState(redis_client)
    prefix = "test:bounded:" + uuid4().hex
    for i in range(1026):
        await state.set(f"{prefix}:{i}", "value", ex=7200)
    assert await redis_client.zcard(STATE_INDEX) <= 1024
    assert await state.get(f"{prefix}:0") is None
    assert 0 < await redis_client.ttl(f"{prefix}:1025") <= 3600
    keys = [key async for key in redis_client.scan_iter(match=f"{prefix}:*")]
    if keys:
        await redis_client.delete(*keys)
        await redis_client.zrem(STATE_INDEX, *keys)


@pytest.mark.asyncio
async def test_restart_preserves_retry_deadline(redis_client):
    queue = MessageQueue(redis_client, uuid4().hex)
    await queue.publish(message())
    delivery = await queue.claim_next()
    assert delivery is not None
    await queue.retry(delivery, 60)
    restarted = MessageQueue(redis_client, queue.queue_name)
    assert await restarted.claim_next() is None


@pytest.mark.asyncio
async def test_redis_failure_keeps_history_and_retry_does_not_duplicate(factory, redis_client):
    from app.services.receiver_service import MessageReceiverService
    queue = MessageQueue(redis_client, uuid4().hex)
    publish = queue.publish
    queue.publish = AsyncMock(side_effect=ConnectionError())  # type: ignore[method-assign]
    receiver = MessageReceiverService(queue, PersonRepository(factory))
    msg = message()
    with pytest.raises(ConnectionError):
        await receiver.handle(msg)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1
    queue.publish = publish  # type: ignore[method-assign]
    await receiver.handle(msg)
    delivery = await queue.claim_next()
    assert delivery is not None and delivery.message.history_id is not None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MessageHistoryModel)) == 1
