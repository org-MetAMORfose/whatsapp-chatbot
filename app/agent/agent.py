import asyncio
import logging
import unicodedata
from dataclasses import dataclass

from app.agent.action_executor import ActionExecutor, ActionResult
from app.agent.chat_flow import ChatFlow, Node
from app.agent.faq_flow import FaqFlow
from app.context import AppContext
from app.domain.message import Message
from app.message_queue import MessageQueue
from app.repository.redis.chat_repository import ChatRepository
from app.repository.redis.patient_stage_repository import PatientStageRepository
from app.repository.redis.professional_stage_repository import ProfessionalStageRepository
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.repository.sql.faq_session_repository import FaqSessionRepository
from app.repository.sql.outbox_repository import OutboxRepository
from app.repository.sql.patient_repository import PatientRepository
from app.repository.sql.person_repository import PersonRepository
from app.repository.sql.professional_repository import ProfessionalRepository
from app.services.s3_media_service import MediaType, S3MediaService

logger = logging.getLogger(__name__)


@dataclass
class Response:
    """Represents a response from the agent after processing a message."""

    content: str
    buttons: list[str] | None = None


class AgentWorker:
    """Agent worker that processes messages from a queue using a chat flow.

    Manages message processing, state transitions, and action execution for the chatbot.
    """

    ctx: AppContext
    inbound_queue: MessageQueue
    outbound_queue: MessageQueue
    flow: ChatFlow
    _task: asyncio.Task[None] | None
    chat_repository: ChatRepository
    action_executor: ActionExecutor

    def __init__(
        self,
        ctx: AppContext,
        inbound: MessageQueue,
        outbound: MessageQueue,
        chat_repository: ChatRepository,
        professional_repository: ProfessionalRepository,
        professional_stage_repository: ProfessionalStageRepository,
        person_repository: PersonRepository,
        patient_repository: PatientRepository,
        patient_stage_repository: PatientStageRepository,
        outbox_repository: OutboxRepository,
        faq_knowledge_repository: FaqKnowledgeRepository,
        faq_session_repository: FaqSessionRepository,
    ):
        self.ctx = ctx
        self.inbound_queue = inbound
        self.outbound_queue = outbound
        self.flow = ChatFlow.from_file()
        self.chat_repository = chat_repository
        faq_flow = FaqFlow(
            person_repository=person_repository,
            session_repository=faq_session_repository,
            knowledge_repository=faq_knowledge_repository,
        )
        self.action_executor = ActionExecutor(
            professional_stage_repository,
            professional_repository,
            person_repository,
            patient_repository,
            patient_stage_repository,
            outbox_repository,
            faq_flow,
        )

    async def _process_message(self, message: Message) -> Response:
        """Process a message from the queue."""
        if not message.content and not message.media:
            logger.warning(
                "Received message with no content: %s",
                message,
            )
            return Response(content="Mensagem vazia recebida.")

        if message.content:
            content = normalize_text(message.content)
        else:
            content = ""

        logger.debug(
            "Processing message content: %s for chat %s",
            content,
            message.chat_id,
        )

        context = await self.chat_repository.get_context(
            user_id=message.user_id,
            channel=message.channel,
        )

        current_state = context.state if context else None

        if content == "reset":
            logger.info(
                "Reset requested by user %s in chat %s",
                message.user_id,
                message.chat_id,
            )

            node = self.flow.get("start")

            if not node or node.get("end"):
                logger.error("No valid start node found.")
                return Response(content="Erro ao reiniciar o fluxo.")

            if context:
                await self.chat_repository.update_context(
                    message,
                    state="start",
                )
            else:
                await self.chat_repository.create_context(
                    user_id=message.user_id,
                    channel=message.channel,
                    state="start",
                )

            return _response_from_node(node)

        if current_state is None:
            current_state = "start"
            node = self.flow.get(current_state)

            if node and not node.get("end"):
                await self.chat_repository.create_context(
                    user_id=message.user_id,
                    channel=message.channel,
                    state=current_state,
                )

                if node.next_transition(content) is None:
                    return _response_from_node(node)

            else:
                return Response(content="Erro ao iniciar o fluxo.")

        node = self.flow.get(current_state)

        if not node:
            logger.error("No node found for state: %s", current_state)
            return Response(content="Erro no fluxo. estado desconhecido.")

        if node.get("end"):
            await self.chat_repository.delete_context(
                user_id=message.user_id,
                channel=message.channel,
            )
            return Response(content=str(node.message))

        required_media_types = _required_media_types(node)
        if required_media_types and not _has_expected_media(
            message,
            required_media_types,
        ):
            if not _allows_text_without_media(node, content):
                requirement = (
                    "um vídeo"
                    if required_media_types == frozenset({"video"})
                    else "o comprovante como imagem ou documento"
                )
                return Response(
                    content=f"Você deve enviar {requirement}.",
                    buttons=node.buttons,
                )

        action_result = await self.action_executor.run(node, message)
        if isinstance(action_result, ActionResult):
            func_output = action_result.output
            action_next_node = action_result.next_node
        else:
            # Allows existing custom executors to keep returning a plain string.
            func_output = action_result
            action_next_node = None

        transition = node.next_transition(content)

        if transition is None:
            logger.info(
                "Invalid response for flow node %s; repeating current node.",
                current_state,
            )
            return _response_from_node(node)

        next_target = action_next_node or transition.target
        if next_target:
            next_node = self.flow.get(next_target)

            if next_node:
                if next_node.get("end"):
                    await self.chat_repository.delete_context(
                        user_id=message.user_id,
                        channel=message.channel,
                    )
                else:
                    await self.chat_repository.update_context(
                        message,
                        state=next_target,
                    )

                content = f"{func_output}{next_node.message}"

                return Response(
                    content=content,
                    buttons=next_node.buttons,
                )

            logger.error("No node found for next_state: %s", next_target)
            return Response(content="Erro no próximo passo.")

        return Response(content="Fim do fluxo.")


def remove_accents(input_str: str) -> str:
    """Remove accents from a string using Unicode normalization.

    Args:
        input_str: The string to remove accents from.

    Returns:
        A string with accents removed.
    """
    # Normalize to NFD (Decomposition)
    nfkd_form = unicodedata.normalize("NFKD", input_str)
    # Filter out characters that are combining marks (Mn category)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


def normalize_text(text: str) -> str:
    """Normalize text by stripping whitespace, converting to lowercase, and removing accents."""
    return remove_accents(text.strip().lower())


def _required_media_types(node: Node) -> frozenset[MediaType]:
    if node.input == "Imagem ou documento":
        return frozenset({"image", "document"})
    if node.input == "Vídeo":
        return frozenset({"video"})
    return frozenset()


def _has_expected_media(
    message: Message,
    expected_types: frozenset[MediaType],
) -> bool:
    if message.media is None:
        return False

    try:
        return S3MediaService.get_media_type(message.media) in expected_types
    except ValueError:
        return False


def _allows_text_without_media(node: Node, content: str) -> bool:
    return any(
        transition.conditions and transition.matches(content)
        for transition in node.transitions
    )


def _response_from_node(node: Node) -> Response:
    return Response(content=str(node.message), buttons=node.buttons)
