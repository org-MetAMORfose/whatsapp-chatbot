"""Download media from WhatsApp, independently of its storage destination."""
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class DownloadedMedia:
    content: bytes
    content_type: str


class WhatsAppMediaService:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    async def download(self, media_id: str) -> DownloadedMedia:
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(timeout=60) as client:
            metadata = await client.get(f"https://graph.facebook.com/v25.0/{media_id}", headers=headers)
            metadata.raise_for_status()
            info = metadata.json()
            response = await client.get(info["url"], headers=headers)
            response.raise_for_status()
            return DownloadedMedia(response.content, info.get("mime_type", "application/octet-stream"))
