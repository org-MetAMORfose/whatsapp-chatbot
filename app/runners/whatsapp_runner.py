import asyncio

import uvicorn
from fastapi import FastAPI

import app.config.settings as config
from app.channel_adapters.whatsapp import WhatsAppAdapter
from app.context import AppContext
from app.controllers.whatsapp_controller import WhatsAppController
from app.message_queue.message_queue import MessageQueue
from app.services.dispatcher_service import MessageDispatcherService
from app.services.receiver_service import MessageReceiverService


class WhatsAppRunner:
    def __init__(
        self,
        ctx: AppContext,
        outbound_queue: MessageQueue,
        message_handler: MessageReceiverService,
    ) -> None:
        self.message_handler = message_handler
        self.whatsapp_adapter = WhatsAppAdapter()

        self.dispatcher = MessageDispatcherService(
            ctx=ctx,
            outbound_queue=outbound_queue,
        )
        self.dispatcher.register_adapter(
            self.whatsapp_adapter.channel,
            self.whatsapp_adapter,
        )

        self.app = FastAPI()
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[None] | None = None

        controller = WhatsAppController(message_handler=message_handler)
        self.app.include_router(controller.router)

    async def start(self) -> None:
        await self.dispatcher.start()

        uvicorn_config = uvicorn.Config(
            self.app,
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