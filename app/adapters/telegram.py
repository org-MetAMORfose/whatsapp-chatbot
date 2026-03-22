import logging
from typing import Any, Callable, Coroutine

import telegram
from telegram.ext import Application, ContextTypes, MessageHandler, filters

import app.config as config
from app.context import AppContext
from app.domain.channels import Channel
from app.domain.message import Message

from . import BotAdapter

logger = logging.getLogger(__name__)

MessageCallback = Callable[[Message], Coroutine[Any, Any, None]]


class TelegramAdapter(BotAdapter):
    channel: Channel = Channel.TELEGRAM
    app: Application | None = None  # type: ignore[type-arg]

    def __init__(self, token: str | None = None, ctx: AppContext | None = None):
        self.ctx = ctx
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.bot = telegram.Bot(token=self.token)

    def send_message(self, message: str) -> None:
        print(f"Sending message to Telegram: {message}")

    def __callback_wrapper(
        self, callback: MessageCallback
    ) -> Callable[
        [telegram.Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]
    ]:
        async def f(
            update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
        ) -> None:
            if not update.effective_chat:
                logger.warning("Update received without effective_chat")
                return

            if not update.message or not update.message.text:
                logger.warning("Update received without message text")
                return

            chat_id = str(update.effective_chat.id)
            user_id = (
                str(update.effective_user.id) if update.effective_user else "ANONYMOUS"
            )
            content = update.message.text

            message = Message(
                channel=self.channel,
                chat_id=chat_id,
                user_id=user_id,
                content=content,
            )

            await callback(message)

        return f

    async def start_listener(self, callback: MessageCallback) -> None:
        self.app = Application.builder().bot(self.bot).build()

        handler = MessageHandler(
            filters.TEXT & ~filters.COMMAND, self.__callback_wrapper(callback)
        )

        self.app.add_handler(handler)
        await self.app.initialize()
        await self.app.start()

        if self.app.updater is not None:
            await self.app.updater.start_polling()

        logger.info("Telegram listener started.")

    async def stop_listener(self) -> None:
        if self.app is not None:
            await self.app.stop()
