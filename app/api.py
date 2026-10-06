"""HTTP ingress and management endpoints, with no background message consumers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.config import infra
from app.controllers.chatbot_flow_controller import ChatbotFlowController
from app.controllers.faq_knowledge_controller import FaqKnowledgeController
from app.controllers.health_controller import HealthController
from app.controllers.matching_follow_up_controller import MatchingFollowUpController
from app.controllers.registration_controller import RegistrationController
from app.controllers.send_message_controller import SendMessageController
from app.controllers.upload_media_controller import UploadMediaController
from app.controllers.whatsapp_controller import WhatsAppController
from app.infra.media_factory import create_media_service
from app.infra.message_queue import MessageQueue
from app.repository.redis.chatbot_flow_cache import ChatFlowCache
from app.repository.redis.matching_follow_up_repository import MatchingFollowUpRepository
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.services.chatbot_flow_admin_service import ChatFlowAdminService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.receiver_service import MessageReceiverService
from app.services.registration_service import RegistrationService


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

    people = PersonRepository(factory)
    outbox = OutboxRepository(factory)
    app = FastAPI(lifespan=lifespan)
    app.include_router(
        WhatsAppController(
            MessageReceiverService(MessageQueue(redis, "inbound"), people),
            outbox,
        ).router
    )
    app.include_router(SendMessageController(MessageQueue(redis, "outbound")).router)
    app.include_router(HealthController(redis).router)
    app.include_router(FaqKnowledgeController(FaqKnowledgeRepository(factory)).router)
    flow_repository = ChatFlowRepository(factory)

    def patient_sheet_tabs() -> list[dict[str, Any]]:
        return [
            {"title": tab.sheet_title, "gid": tab.gid}
            for tab in GoogleSheetsService().list_patient_tabs()
        ]

    app.include_router(
        ChatbotFlowController(
            ChatFlowAdminService(
                factory,
                ChatFlowCache(redis, flow_repository),
                sheet_tabs_provider=patient_sheet_tabs,
            )
        ).router
    )
    patients = PatientRepository(factory)
    professionals = ProfessionalRepository(factory)
    app.include_router(
        RegistrationController(
            RegistrationService(
                factory,
                people,
                patients,
                professionals,
                outbox,
            )
        ).router
    )
    app.include_router(
        MatchingFollowUpController(
            people,
            patients,
            professionals,
            WhatsAppAdapter(),
            MatchingFollowUpRepository(redis),
        ).router
    )
    media = create_media_service()
    if media is not None:
        app.include_router(UploadMediaController(media).router)
    return app
