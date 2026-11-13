from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enum.channels import Channel
from app.repository.redis.immediate_offer_repository import ImmediateOfferRepository

KEY = "immediate_offer:WHATSAPP:5511999991111"


@pytest.mark.asyncio
async def test_mark_get_clear_with_ttl() -> None:
    repository = ImmediateOfferRepository(MagicMock())
    state = MagicMock()
    state.set = AsyncMock()
    state.get = AsyncMock(side_effect=["42", None, "oops"])
    state.delete = AsyncMock(return_value=1)
    repository.redis_client = state

    await repository.mark("5511999991111", Channel.WHATSAPP, 42, ttl_seconds=300)
    state.set.assert_awaited_once_with(KEY, "42", ex=300)
    assert await repository.get("5511999991111", Channel.WHATSAPP) == 42
    assert await repository.get("5511999991111", Channel.WHATSAPP) is None
    assert await repository.get("5511999991111", Channel.WHATSAPP) is None
    await repository.clear("5511999991111", Channel.WHATSAPP)
    state.delete.assert_awaited_once_with(KEY)


@pytest.mark.asyncio
async def test_mark_rejects_non_positive_ttl() -> None:
    repository = ImmediateOfferRepository(MagicMock())
    repository.redis_client = MagicMock(set=AsyncMock())
    with pytest.raises(ValueError):
        await repository.mark("5511999991111", Channel.WHATSAPP, 42, ttl_seconds=0)
