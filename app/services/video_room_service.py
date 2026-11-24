"""Video rooms for immediate care sessions: Daily in production, a fake URL in development.

The room is private: the bare room URL lets nobody in. Each person gets a join link with their own
meeting token (Daily `?t=`), valid until the room expires, sent only by WhatsApp.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

import app.config.settings as settings

DAILY_API_URL = "https://api.daily.co/v1"


@dataclass(frozen=True)
class VideoRoom:
    room_url: str  # without a token: safe to show in the panel, does not open the session
    patient_url: str
    professional_url: str


class VideoRoomService(Protocol):
    async def create_room(self, *, name: str, expires_at: datetime) -> VideoRoom: ...


class DailyService:
    """Private room for two, ejected at expiry. Recording and transcription are never started by this code."""

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._api_key = api_key
        self._transport = transport

    async def create_room(self, *, name: str, expires_at: datetime) -> VideoRoom:
        exp = int(expires_at.timestamp())
        room = {
            "name": name,
            "privacy": "private",
            "properties": {"exp": exp, "max_participants": 2, "eject_at_room_exp": True, "enable_prejoin_ui": True, "enable_knocking": False},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            response = await client.post(f"{DAILY_API_URL}/rooms", headers=headers, json=room)
            _raise_for_status(response, "rooms")
            url = response.json().get("url")
            if not isinstance(url, str) or not url:
                raise RuntimeError("Daily did not return a room URL")
            patient = await self._token(client, headers, name, exp, "Paciente")
            professional = await self._token(client, headers, name, exp, "Profissional")
        return VideoRoom(room_url=url, patient_url=f"{url}?t={patient}", professional_url=f"{url}?t={professional}")

    @staticmethod
    async def _token(client: httpx.AsyncClient, headers: dict[str, str], room: str, exp: int, user_name: str) -> str:
        properties = {"room_name": room, "exp": exp, "user_name": user_name, "is_owner": False, "eject_at_token_exp": True}
        response = await client.post(f"{DAILY_API_URL}/meeting-tokens", headers=headers, json={"properties": properties})
        _raise_for_status(response, "meeting-tokens")
        token = response.json().get("token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Daily did not return a meeting token")
        return token


def _raise_for_status(response: httpx.Response, path: str) -> None:
    if response.is_error:
        raise RuntimeError(f"Daily {path} returned HTTP {response.status_code}")


class FakeVideoRoomService:
    async def create_room(self, *, name: str, expires_at: datetime) -> VideoRoom:
        url = f"https://exemplo.daily.co/{name}"
        return VideoRoom(room_url=url, patient_url=f"{url}?t=paciente", professional_url=f"{url}?t=profissional")


def video_room_service_from_settings() -> VideoRoomService:
    if settings.DAILY_API_KEY:
        return DailyService(settings.DAILY_API_KEY)
    # Without the key the feature stays closed (immediate_care_config), so the fake room never reaches a patient.
    return FakeVideoRoomService()
