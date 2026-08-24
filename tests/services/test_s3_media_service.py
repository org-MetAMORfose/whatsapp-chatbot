from unittest.mock import MagicMock, patch

import pytest

from app.services.s3_media_service import S3MediaService


def _make_service(s3_client: MagicMock) -> S3MediaService:
    with patch(
        "app.services.s3_media_service.boto3.client",
        return_value=s3_client,
    ):
        return S3MediaService(
            whatsapp_token="whatsapp-token",
            bucket="private-media-bucket",
            region="us-east-1",
            aws_access_key_id="access-key",
            aws_secret_access_key="secret-key",
        )


@pytest.mark.asyncio
async def test_upload_file_returns_path_instead_of_url() -> None:
    s3_client = MagicMock()
    service = _make_service(s3_client)
    fake_uuid = MagicMock(hex="abc123")

    with patch("app.services.s3_media_service.uuid4", return_value=fake_uuid):
        media_path = await service.upload_file(
            file_bytes=b"image-bytes",
            content_type="image/png",
            media_type="image",
            filename="photo.png",
        )

    assert media_path == "media/image/abc123.png"
    s3_client.put_object.assert_called_once_with(
        Bucket="private-media-bucket",
        Key=media_path,
        Body=b"image-bytes",
        ContentType="image/png",
    )


@pytest.mark.asyncio
async def test_get_file_reads_private_s3_object_by_path() -> None:
    body = MagicMock()
    body.read.return_value = b"document-bytes"
    s3_client = MagicMock()
    s3_client.get_object.return_value = {
        "Body": body,
        "ContentType": "application/pdf",
    }
    service = _make_service(s3_client)

    media = await service.get_file("media/document/registration.pdf")

    assert media.path == "media/document/registration.pdf"
    assert media.content == b"document-bytes"
    assert media.content_type == "application/pdf"
    assert media.filename == "registration.pdf"
    s3_client.get_object.assert_called_once_with(
        Bucket="private-media-bucket",
        Key="media/document/registration.pdf",
    )


@pytest.mark.parametrize(
    "media_path",
    [
        "/media/image/file.png",
        "https://bucket/media/image/file.png",
        "media/image/../secret.txt",
        "media/video/file.mp4",
        "media/image/file.png?signature=secret",
    ],
)
def test_validate_media_path_rejects_non_media_keys(media_path: str) -> None:
    with pytest.raises(ValueError):
        S3MediaService.validate_media_path(media_path)
