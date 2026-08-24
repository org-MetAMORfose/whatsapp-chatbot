import asyncio
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import boto3
import httpx

logger = logging.getLogger(__name__)

_WHATSAPP_API_BASE = "https://graph.facebook.com/v23.0"
MediaType = Literal["image", "document"]


@dataclass(frozen=True)
class StoredMedia:
    """Media bytes and metadata loaded from S3."""

    path: str
    content: bytes
    content_type: str
    filename: str


class S3MediaService:
    def __init__(
        self,
        whatsapp_token: str,
        bucket: str,
        region: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
    ) -> None:
        self._token = whatsapp_token
        self._bucket = bucket
        self._region = region
        self._s3 = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=aws_access_key_id or None,
            aws_secret_access_key=aws_secret_access_key or None,
        )

    async def upload_file(
        self,
        file_bytes: bytes,
        content_type: str,
        media_type: str,
        filename: str | None = None,
    ) -> str:
        """Upload generic media bytes to S3 and return its stable object path."""
        if media_type not in {"image", "document"}:
            raise ValueError("media_type must be 'image' or 'document'")

        extension = ""
        if filename:
            extension = Path(filename).suffix
        if not extension:
            extension = mimetypes.guess_extension(
                content_type.split(";")[0].strip()
            ) or ""

        key = f"media/{media_type}/{uuid4().hex}{extension}"

        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )

        logger.info("Uploaded file to S3 (key=%s)", key)
        return key

    async def upload_from_whatsapp(self, media_id: str, media_type: str) -> str:
        """Download WhatsApp media, store it in S3, and return its object path."""
        if media_type not in {"image", "document"}:
            raise ValueError("media_type must be 'image' or 'document'")

        headers = {"Authorization": f"Bearer {self._token}"}

        async with httpx.AsyncClient() as client:
            meta_resp = await client.get(
                f"{_WHATSAPP_API_BASE}/{media_id}",
                headers=headers,
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            download_url: str = meta["url"]
            mime_type: str = meta.get("mime_type", "application/octet-stream")

            file_resp = await client.get(download_url, headers=headers)
            file_resp.raise_for_status()
            file_bytes = file_resp.content

        ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) or ""
        key = f"media/{media_type}/{media_id}{ext}"

        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=file_bytes,
            ContentType=mime_type,
        )

        logger.info("Uploaded WhatsApp media %s to S3 (key=%s)", media_id, key)
        return key

    async def get_file(self, media_path: str) -> StoredMedia:
        """Load a stored media object directly from the private S3 bucket."""
        self.validate_media_path(media_path)

        response = await asyncio.to_thread(
            self._s3.get_object,
            Bucket=self._bucket,
            Key=media_path,
        )
        content = await asyncio.to_thread(response["Body"].read)
        content_type = str(
            response.get("ContentType")
            or mimetypes.guess_type(media_path)[0]
            or "application/octet-stream"
        )

        return StoredMedia(
            path=media_path,
            content=content,
            content_type=content_type,
            filename=Path(media_path).name,
        )

    @staticmethod
    def validate_media_path(media_path: str) -> None:
        """Reject keys outside the application's media prefixes."""
        if (
            not media_path
            or media_path.startswith("/")
            or "://" in media_path
            or "?" in media_path
            or "#" in media_path
            or "\\" in media_path
        ):
            raise ValueError("media_path must be a relative S3 object path")

        parts = media_path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("invalid media_path")

        if not media_path.startswith(("media/image/", "media/document/")):
            raise ValueError("media_path must point to image or document media")

    @classmethod
    def get_media_type(cls, media_path: str) -> MediaType:
        """Infer the media category from its validated S3 object path."""
        cls.validate_media_path(media_path)
        if media_path.startswith("media/image/"):
            return "image"
        return "document"
