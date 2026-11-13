import json
from datetime import UTC, datetime

import httpx
import pytest

import app.config.settings as settings
from app.services.video_room_service import DailyService, FakeVideoRoomService, video_room_service_from_settings

EXPIRES = datetime(2026, 11, 12, 21, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_daily_creates_public_room_with_expiry():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "x", "name": "acolhimento-1-abc", "url": "https://metamorfose.daily.co/acolhimento-1-abc"})

    service = DailyService("k", transport=httpx.MockTransport(handler))
    url = await service.create_room(name="acolhimento-1-abc", expires_at=EXPIRES)
    assert url == "https://metamorfose.daily.co/acolhimento-1-abc"
    request = calls[0]
    assert request.method == "POST" and str(request.url) == "https://api.daily.co/v1/rooms"
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content) == {
        "name": "acolhimento-1-abc",
        "privacy": "public",
        "properties": {"exp": int(EXPIRES.timestamp()), "max_participants": 2, "eject_at_room_exp": True, "enable_prejoin_ui": True},
    }


@pytest.mark.asyncio
async def test_daily_raises_on_http_error():
    service = DailyService("k", transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "nope"})))
    with pytest.raises(httpx.HTTPStatusError):
        await service.create_room(name="acolhimento-1-abc", expires_at=EXPIRES)


@pytest.mark.asyncio
async def test_fake_room_url():
    assert await FakeVideoRoomService().create_room(name="acolhimento-7-abc", expires_at=EXPIRES) == "https://exemplo.daily.co/acolhimento-7-abc"


def test_from_settings_selects_fake_without_key(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_API_KEY", "")
    assert isinstance(video_room_service_from_settings(), FakeVideoRoomService)
    monkeypatch.setattr(settings, "DAILY_API_KEY", "k")
    assert isinstance(video_room_service_from_settings(), DailyService)


def test_from_settings_refuses_fake_room_with_the_feature_on(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_API_KEY", "")
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", False)
    with pytest.raises(RuntimeError, match="DAILY_API_KEY"):
        video_room_service_from_settings()
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", True)
    assert isinstance(video_room_service_from_settings(), FakeVideoRoomService)
