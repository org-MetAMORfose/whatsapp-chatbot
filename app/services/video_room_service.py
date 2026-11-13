"""Video rooms for immediate care sessions: Daily in production, a fake URL in development."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

import httpx

import app.config.settings as settings

DAILY_ROOMS_URL = "https://api.daily.co/v1/rooms"


class VideoRoomService(Protocol):
    async def create_room(self, *, name: str, expires_at: datetime) -> str: ...


class DailyService:
    """Public room, two participants, ejected at expiry, no recording (Daily does not record unless asked)."""

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._transport = transport

    async def create_room(self, *, name: str, expires_at: datetime) -> str:
        payload = {
            "name": name,
            "privacy": "public",
            "properties": {"exp": int(expires_at.timestamp()), "max_participants": 2, "eject_at_room_exp": True, "enable_prejoin_ui": True},
        }
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            response = await client.post(DAILY_ROOMS_URL, headers={"Authorization": f"Bearer {self._api_key}"}, json=payload)
        response.raise_for_status()
        url = response.json().get("url")
        if not isinstance(url, str) or not url:
            raise RuntimeError("Daily did not return a room URL")
        return url


class FakeVideoRoomService:
    async def create_room(self, *, name: str, expires_at: datetime) -> str:
        return f"https://exemplo.daily.co/{name}"


def video_room_service_from_settings() -> VideoRoomService:
    if settings.DAILY_API_KEY:
        return DailyService(settings.DAILY_API_KEY)
    return FakeVideoRoomService()
