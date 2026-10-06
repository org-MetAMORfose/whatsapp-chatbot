import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.enum.channels import Channel
from app.domain.message import Message
from app.repository.redis.sheets_stage_repository import SheetsStageRepository


def message() -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=datetime(2026, 6, 22),
        user_id="5511999999999",
        chat_id="chat-1",
        content="Nova resposta",
    )


@pytest.mark.asyncio
async def test_store_overwrites_column_and_refreshes_one_hour_ttl() -> None:
    repository = object.__new__(SheetsStageRepository)
    staged = MagicMock()
    staged.get = AsyncMock(return_value=json.dumps({"G": "Resposta anterior", "H": "TCC"}))
    staged.set = AsyncMock()
    repository.redis_client = staged
    current = message()

    await repository.store(current, "Pacientes", "G", "Nova resposta")

    _, payload = staged.set.call_args.args
    assert json.loads(payload) == {"G": "Nova resposta", "H": "TCC"}
    assert staged.set.call_args.kwargs == {"ex": 3600}


@pytest.mark.asyncio
async def test_tabs_and_users_have_distinct_keys() -> None:
    first = message()
    second = first.model_copy(update={"user_id": "5511888888888"})

    assert SheetsStageRepository._key(first, "Aba 1") != SheetsStageRepository._key(first, "Aba 2")
    assert SheetsStageRepository._key(first, "Aba 1") != SheetsStageRepository._key(second, "Aba 1")
