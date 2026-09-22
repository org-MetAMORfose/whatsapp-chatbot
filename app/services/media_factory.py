from app.config import settings
from app.services.s3_media_service import S3MediaService


def create_media_service() -> S3MediaService | None:
    if not settings.S3_BUCKET_NAME:
        return None
    return S3MediaService(
        whatsapp_token=settings.WHATSAPP_ACCESS_TOKEN, bucket=settings.S3_BUCKET_NAME,
        region=settings.AWS_REGION, aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )
