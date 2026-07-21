#!/usr/bin/env python3
import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from app.agent.agent import AgentWorker
from app.agent.chat_flow import ChatFlow
from app.domain.chat import ChatContext
from app.domain.enum.channels import Channel
from app.domain.enum.chat_mode import ChatMode
from app.domain.message import Message


class FakeChatRepository:
    def __init__(self, state: str | None = None) -> None:
        self.context: ChatContext | None = None
        self.created_state: str | None = None
        self.updated_state: str | None = None
        self.deleted = False

        if state is not None:
            self.context = ChatContext(
                user_id="11939016277",
                channel=Channel.WHATSAPP,
                state=state,
            )

    async def get_context(self, user_id: str, channel: Channel) -> ChatContext | None:
        return self.context

    async def create_context(self, user_id: str, channel: Channel, state: str) -> ChatContext:
        self.created_state = state
        self.context = ChatContext(user_id=user_id, channel=channel, state=state)
        return self.context

    async def update_context(self, message: Message, state: str) -> ChatContext:
        self.updated_state = state
        if self.context is None:
            self.context = ChatContext(
                user_id=message.user_id,
                channel=message.channel,
                state=state,
            )
        else:
            self.context.state = state
        return self.context

    async def delete_context(self, user_id: str, channel: Channel) -> bool:
        self.deleted = True
        self.context = None
        return True


def make_message(content: str | None) -> Message:
    return Message(
        message_id=1,
        channel=Channel.WHATSAPP,
        created_at=None,
        user_id="11939016277",
        chat_id="11939016277",
        content=content,
    )


async def main() -> None:
    person_repository = MagicMock()
    person_repository.update_chat_mode_by_contact = MagicMock(return_value=True)
    person_repository.update_chat_state_by_contact = MagicMock(return_value=True)

    worker = AgentWorker(
        ctx=MagicMock(),
        inbound=MagicMock(),
        outbound=MagicMock(),
        chat_repository=FakeChatRepository(),
        professional_repository=MagicMock(),
        professional_stage_repository=MagicMock(),
        person_repository=cast(Any, person_repository),
    )
    worker.flow = ChatFlow.from_file()

    responses = []
    for content in ("oi", "sou profissional", "duvidas"):
        response = await worker._process_message(make_message(content))
        responses.append(response)

    person_repository.update_chat_mode_by_contact.assert_called_once_with(
        phone_number="11939016277",
        channel=Channel.WHATSAPP,
        chat_mode=ChatMode.MANUAL,
    )

    print("== Local smoke test: dúvida/IA handoff ==")
    print("1) start ->", responses[0].content.strip().splitlines()[0])
    print("2) profissional_start ->", responses[1].content.strip().splitlines()[0])
    print("3) faq_inicio ->", responses[2].content.strip().splitlines()[0])
    print("4) person_repository.update_chat_mode_by_contact called:", True)


if __name__ == "__main__":
    asyncio.run(main())
