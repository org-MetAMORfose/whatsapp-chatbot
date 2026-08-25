from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.controllers.upload_media_controller import UploadMediaController
from app.services.s3_media_service import S3MediaService


@pytest.mark.asyncio
async def test_upload_media_endpoint_returns_path() -> None:
    mock_s3_service = MagicMock(spec=S3MediaService)
    mock_s3_service.upload_file = AsyncMock(return_value="media/image/test.jpg")

    app = FastAPI()
    controller = UploadMediaController(s3_service=mock_s3_service)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post(
        "/upload-media",
        data={"media_type": "image"},
        files={"file": ("test.jpg", b"file-bytes", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {"media": "media/image/test.jpg"}
    mock_s3_service.upload_file.assert_awaited_once()


def test_upload_media_endpoint_returns_400_for_invalid_media_type() -> None:
    mock_s3_service = MagicMock(spec=S3MediaService)
    mock_s3_service.upload_file = AsyncMock()

    app = FastAPI()
    controller = UploadMediaController(s3_service=mock_s3_service)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post(
        "/upload-media",
        data={"media_type": "audio"},
        files={"file": ("test.mp3", b"file-bytes", "audio/mpeg")},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "media_type must be 'image', 'document' or 'video'"
    )


def test_upload_media_endpoint_accepts_video() -> None:
    mock_s3_service = MagicMock(spec=S3MediaService)
    mock_s3_service.upload_file = AsyncMock(return_value="media/video/test.mp4")

    app = FastAPI()
    controller = UploadMediaController(s3_service=mock_s3_service)
    app.include_router(controller.router)

    client = TestClient(app)
    response = client.post(
        "/upload-media",
        data={"media_type": "video"},
        files={"file": ("test.mp4", b"video-bytes", "video/mp4")},
    )

    assert response.status_code == 200
    assert response.json() == {"media": "media/video/test.mp4"}
    mock_s3_service.upload_file.assert_awaited_once_with(
        file_bytes=b"video-bytes",
        content_type="video/mp4",
        media_type="video",
        filename="test.mp4",
    )
