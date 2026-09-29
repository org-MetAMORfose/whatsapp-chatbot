from unittest.mock import patch

import httpx
import pytest

from app.services.whatsapp_media_service import WhatsAppMediaService


@pytest.mark.asyncio
async def test_download_returns_bytes_and_mime_without_s3() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer token"
        if request.url.host == "graph.facebook.com":
            return httpx.Response(200, json={"url": "https://media.example/file", "mime_type": "video/mp4"})
        return httpx.Response(200, content=b"video-bytes")

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    with patch("app.services.whatsapp_media_service.httpx.AsyncClient", return_value=client):
        downloaded = await WhatsAppMediaService("token").download("media-id")
    assert downloaded.content == b"video-bytes"
    assert downloaded.content_type == "video/mp4"
