import asyncio
import logging
import mimetypes

import boto3
import httpx

logger = logging.getLogger(__name__)

_WHATSAPP_API_BASE = "https://graph.facebook.com/v23.0"


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

    async def upload_from_whatsapp(self, media_id: str, media_type: str) -> str:
        """Download a WhatsApp media object and upload it to S3. Returns the S3 URL."""
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

        s3_url = f"https://{self._bucket}.s3.{self._region}.amazonaws.com/{key}"
        logger.info("Uploaded WhatsApp media %s to %s", media_id, s3_url)
        return s3_url
