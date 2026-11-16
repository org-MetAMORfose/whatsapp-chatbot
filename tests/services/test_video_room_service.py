import json
from datetime import UTC, datetime

import httpx
import pytest

import app.config.settings as settings
from app.services.immediate_care_config import immediate_care_enabled
from app.services.video_room_service import DailyService, FakeVideoRoomService, VideoRoom, video_room_service_from_settings

EXPIRES = datetime(2026, 11, 12, 21, 0, tzinfo=UTC)
ROOM_URL = "https://metamorfose.daily.co/acolhimento-1-abc"


def daily(calls: list[httpx.Request]) -> DailyService:
    tokens = iter(["token-paciente", "token-profissional"])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/rooms":
            return httpx.Response(200, json={"id": "x", "name": "acolhimento-1-abc", "url": ROOM_URL})
        return httpx.Response(200, json={"token": next(tokens)})

    return DailyService("k", transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_daily_creates_a_private_room_and_one_token_per_person():
    calls: list[httpx.Request] = []
    room = await daily(calls).create_room(name="acolhimento-1-abc", expires_at=EXPIRES)

    assert room == VideoRoom(
        room_url=ROOM_URL,
        patient_url=f"{ROOM_URL}?t=token-paciente",
        professional_url=f"{ROOM_URL}?t=token-profissional",
    )
    assert all(request.headers["Authorization"] == "Bearer k" for request in calls)
    assert json.loads(calls[0].content) == {
        "name": "acolhimento-1-abc",
        "privacy": "private",
        "properties": {
            "exp": int(EXPIRES.timestamp()),
            "max_participants": 2,
            "eject_at_room_exp": True,
            "enable_prejoin_ui": True,
            "enable_knocking": False,
        },
    }
    token_bodies = [json.loads(request.content)["properties"] for request in calls[1:]]
    assert [str(request.url) for request in calls[1:]] == ["https://api.daily.co/v1/meeting-tokens"] * 2
    assert token_bodies == [
        {"room_name": "acolhimento-1-abc", "exp": int(EXPIRES.timestamp()), "user_name": name, "is_owner": False, "eject_at_token_exp": True}
        for name in ("Paciente", "Psicólogo(a)")
    ]
    assert not any("recording" in key for body in token_bodies for key in body)


@pytest.mark.asyncio
async def test_daily_raises_on_http_error():
    service = DailyService("k", transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "nope"})))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        await service.create_room(name="acolhimento-1-abc", expires_at=EXPIRES)


@pytest.mark.asyncio
async def test_daily_raises_when_a_token_is_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/rooms":
            return httpx.Response(200, json={"url": ROOM_URL})
        return httpx.Response(200, json={})

    with pytest.raises(RuntimeError, match="meeting token"):
        await DailyService("k", transport=httpx.MockTransport(handler)).create_room(name="acolhimento-1-abc", expires_at=EXPIRES)


@pytest.mark.asyncio
async def test_fake_room_has_per_person_links():
    room = await FakeVideoRoomService().create_room(name="acolhimento-7-abc", expires_at=EXPIRES)
    assert room.room_url == "https://exemplo.daily.co/acolhimento-7-abc"
    assert room.patient_url != room.professional_url


def test_from_settings_selects_fake_without_key(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_API_KEY", "")
    assert isinstance(video_room_service_from_settings(), FakeVideoRoomService)
    monkeypatch.setattr(settings, "DAILY_API_KEY", "k")
    assert isinstance(video_room_service_from_settings(), DailyService)


def test_switch_on_without_the_daily_key_keeps_the_feature_closed(monkeypatch):
    monkeypatch.setattr(settings, "DAILY_API_KEY", "")
    monkeypatch.setattr(settings, "IMMEDIATE_CARE_ENABLED", True)
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", False)
    assert not immediate_care_enabled()
    monkeypatch.setattr(settings, "IMMEDIATE_ALLOW_FAKE", True)
    assert immediate_care_enabled()
