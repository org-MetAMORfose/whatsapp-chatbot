from app.channel_adapters.telegram import TelegramAdapter
from app.context import AppContext
from app.message_queue.message_queue import MessageQueue
from app.repository.person_repository import PersonRepository
from app.services.dispatcher_service import MessageDispatcherService
from app.services.receiver_service import MessageReceiverService


class TelegramRunner:
    def __init__(
        self,
        ctx: AppContext,
        outbound_queue: MessageQueue,
        message_receiver: MessageReceiverService,
        person_repository: PersonRepository,
        token: str | None = None,
    ) -> None:
        self.telegram_adapter = TelegramAdapter(ctx=ctx, token=token)
        self.message_receiver = message_receiver
        self.dispatcher = MessageDispatcherService(
            ctx=ctx,
            outbound_queue=outbound_queue,
            person_repository=person_repository,
        )

        self.dispatcher.register_adapter(
            self.telegram_adapter.channel,
            self.telegram_adapter,
        )

    async def start(self) -> None:
        await self.dispatcher.start()
        await self.telegram_adapter.start_listener(callback=self.message_receiver.handle)

    async def stop(self) -> None:
        await self.telegram_adapter.stop_listener()
        await self.dispatcher.stop()
