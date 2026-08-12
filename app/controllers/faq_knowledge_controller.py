"""Authenticated endpoint for adding entries to the FAQ knowledge base."""

import logging
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from openai import OpenAIError
from pydantic import BaseModel, Field

import app.config.settings as config
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.services.faq_knowledge_service import FaqKnowledgeService
from app.services.openai_service import OpenAIConfigurationError, OpenAIService

logger = logging.getLogger(__name__)


class CreateFaqKnowledgeEntryRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class CreateFaqKnowledgeEntryResponse(BaseModel):
    id: int
    embedding_model: str
    created_at: datetime


class FaqKnowledgeController:
    """Expose administrative writes to the FAQ knowledge base."""

    def __init__(
        self,
        repository: FaqKnowledgeRepository,
        openai_service: OpenAIService | None = None,
    ) -> None:
        self.service = FaqKnowledgeService(repository, openai_service)
        self.router = APIRouter()
        self.router.add_api_route(
            "/faq/knowledge-entries",
            self.create_entry,
            methods=["POST"],
            response_model=CreateFaqKnowledgeEntryResponse,
            status_code=status.HTTP_201_CREATED,
        )

    async def create_entry(
        self,
        body: CreateFaqKnowledgeEntryRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> CreateFaqKnowledgeEntryResponse:
        self._authenticate(chatbot_api_key)
        try:
            entry = await self.service.create_entry(
                question=body.question,
                answer=body.answer,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        except OpenAIConfigurationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI integration is not configured.",
            ) from exc
        except OpenAIError as exc:
            logger.exception("Failed to generate an embedding for an FAQ entry")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to generate the FAQ embedding.",
            ) from exc

        return CreateFaqKnowledgeEntryResponse(
            id=entry.id,
            embedding_model=entry.embedding_model,
            created_at=entry.created_at,
        )

    @staticmethod
    def _authenticate(provided_key: str | None) -> None:
        expected_key = config.CHATBOT_API_KEY
        if not expected_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chatbot API authentication is not configured.",
            )
        if provided_key is None or not secrets.compare_digest(
            provided_key,
            expected_key,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid chatbot API key.",
            )
