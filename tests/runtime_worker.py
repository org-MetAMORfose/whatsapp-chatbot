"""Memory/smoke harness: production worker, local substitutes for external providers.

Mount this file into an isolated test container and set DELIVERY_RUNTIME_TEST=1.
Never use this entry point in production.
"""
import asyncio
import os
from typing import Any
from unittest.mock import patch

from google.auth.credentials import AnonymousCredentials
from google.auth.transport.requests import AuthorizedSession
from openai import AsyncOpenAI

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.config.infra import create_redis
from app.domain.message import Message
from app.services.google_sheets_service import GoogleSheetsService
from app.worker import run

if os.environ.get("DELIVERY_RUNTIME_TEST") != "1":
    raise SystemExit("This entry point is only for isolated runtime tests")


class LocalSheets(GoogleSheetsService):
    def __init__(self) -> None:
        super().__init__(client=AuthorizedSession(AnonymousCredentials()),  # type: ignore[no-untyped-call]
                         patients_spreadsheet_url="https://docs.google.com/spreadsheets/d/test/edit#gid=0",
                         professionals_spreadsheet_url="https://docs.google.com/spreadsheets/d/test/edit#gid=0")

    def _request(self, method: str, path: str, *, params: dict[str, str] | None = None,
                 body: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"sheets": [{"properties": {"sheetId": 0, "title": "Test"}}], "values": []}


async def send(self: WhatsAppAdapter, message: Message) -> None:
    await self._parse_message(message)
    client = create_redis()
    try:
        await client.incr("test:sent")
    finally:
        await client.aclose()


async def main() -> None:
    # Keep a real SDK client initialized to include its memory cost, without API requests.
    async with AsyncOpenAI(api_key="test-only"):
        with patch("app.channel_adapters.whatsapp.WhatsAppAdapter.send_message", send), \
                patch("app.services.google_sheets_service.GoogleSheetsService", LocalSheets):
            await run()


if __name__ == "__main__":
    asyncio.run(main())
