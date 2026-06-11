import asyncio

import uvicorn
from fastapi import FastAPI

import app.config.settings as config
from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.controllers.health_controller import HealthController
from app.controllers.send_message_controller import SendMessageController
from app.controllers.upload_media_controller import UploadMediaController
from app.controllers.whatsapp_controller import WhatsAppController
from app.message_queue.message_queue import MessageQueue
from app.repository.person_repository import PersonRepository
from app.services.dispatcher_service import MessageDispatcherService
from app.services.receiver_service import MessageReceiverService
from app.services.s3_media_service import S3MediaService


class WhatsAppRunner:
    def __init__(
        self,
        ctx: AppContext,
        outbound_queue: MessageQueue,
        message_handler: MessageReceiverService,
        person_repository: PersonRepository,
    ) -> None:
        self.message_handler = message_handler
        self.whatsapp_adapter = WhatsAppAdapter()

        self.dispatcher = MessageDispatcherService(
            ctx=ctx,
            outbound_queue=outbound_queue,
            person_repository=person_repository,
        )
        self.dispatcher.register_adapter(
            self.whatsapp_adapter.channel,
            self.whatsapp_adapter,
        )

        self.app = FastAPI()
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[None] | None = None

        s3_service = S3MediaService(
            whatsapp_token=config.WHATSAPP_ACCESS_TOKEN,
            bucket=config.S3_BUCKET_NAME,
            region=config.AWS_REGION,
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
        ) if config.S3_BUCKET_NAME else None

        controller = WhatsAppController(message_handler=message_handler, s3_service=s3_service)
        health_controller = HealthController()
        send_message_controller = SendMessageController(
            dispatcher=self.dispatcher)
        self.app.include_router(controller.router)
        self.app.include_router(health_controller.router)
        self.app.include_router(send_message_controller.router)

        if s3_service is not None:
            upload_media_controller = UploadMediaController(s3_service=s3_service)
            self.app.include_router(upload_media_controller.router)

    async def start(self) -> None:
        await self.dispatcher.start()

        uvicorn_config = uvicorn.Config(
            self.app,
            port=config.WHATSAPP_WEBHOOK_PORT,
            host="0.0.0.0",  # noqa: S104
            log_level=config.LOG_LEVEL.lower(),
        )
        self.server = uvicorn.Server(uvicorn_config)
        self.server_task = asyncio.create_task(self.server.serve())

    async def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

        if self.server_task is not None:
            await self.server_task

        await self.dispatcher.stop()
