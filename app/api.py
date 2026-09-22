"""HTTP ingress and management endpoints, with no background message consumers."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import infra
from app.controllers.faq_knowledge_controller import FaqKnowledgeController
from app.controllers.health_controller import HealthController
from app.controllers.send_message_controller import SendMessageController
from app.controllers.upload_media_controller import UploadMediaController
from app.controllers.whatsapp_controller import WhatsAppController
from app.message_queue import MessageQueue
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.services.media_factory import create_media_service
from app.services.receiver_service import MessageReceiverService


def create_app() -> FastAPI:
    redis = infra.create_redis()
    engine = infra.create_db_engine()
    factory = infra.create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await redis.ping()
        try:
            yield
        finally:
            await redis.aclose()  # type: ignore[attr-defined]
            engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(WhatsAppController(MessageReceiverService(MessageQueue(redis, "inbound"))).router)
    app.include_router(SendMessageController(MessageQueue(redis, "outbound")).router)
    app.include_router(HealthController(redis).router)
    app.include_router(FaqKnowledgeController(FaqKnowledgeRepository(factory)).router)
    media = create_media_service()
    if media is not None:
        app.include_router(UploadMediaController(media).router)
    return app
