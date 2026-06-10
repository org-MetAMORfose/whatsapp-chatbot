import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.s3_media_service import S3MediaService

logger = logging.getLogger(__name__)


class UploadMediaResponse(BaseModel):
    url: str


class UploadMediaController:
    def __init__(self, s3_service: S3MediaService) -> None:
        self.s3_service = s3_service
        self.router = APIRouter()

        self.router.add_api_route(
            "/upload-media",
            self.upload_media,
            methods=["POST"],
            response_model=UploadMediaResponse,
        )

    async def upload_media(
        self,
        media_type: Annotated[str, Form()] = "image",
        file: Annotated[UploadFile, File(...)] = None, # Or just leave = File(...) out if using Annotated
    ) -> UploadMediaResponse:
        if media_type not in {"image", "document"}:
            raise HTTPException(
                status_code=400,
                detail="media_type must be 'image' or 'document'",
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        content_type = file.content_type or "application/octet-stream"

        try:
            url = await self.s3_service.upload_file(
                file_bytes=file_bytes,
                content_type=content_type,
                media_type=media_type,
                filename=file.filename,
            )
        except Exception as exc:
            logger.exception("Failed to upload media to S3")
            raise HTTPException(
                status_code=500,
                detail="Failed to upload media to S3",
            ) from exc

        return UploadMediaResponse(url=url)
