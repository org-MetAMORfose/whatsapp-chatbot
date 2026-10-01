"""Authenticated endpoints for managing the FAQ knowledge base."""

import logging
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

import app.config.settings as config
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeRepository
from app.services.faq_knowledge_service import (
    FaqKnowledgeEntryNotFoundError,
    FaqKnowledgeGroup,
    FaqKnowledgeGroupNotFoundError,
    FaqKnowledgeService,
)
from app.services.openai_service import OpenAIConfigurationError, OpenAIService

logger = logging.getLogger(__name__)


class CreateFaqKnowledgeEntryRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class CreateFaqKnowledgeEntryResponse(BaseModel):
    id: int
    embedding_model: str
    created_at: datetime


class CreateFaqGroupRequest(BaseModel):
    answer: str = Field(min_length=1)
    questions: list[str] = Field(min_length=1)


class UpdateFaqGroupRequest(BaseModel):
    answer: str = Field(min_length=1)


class AddFaqQuestionRequest(BaseModel):
    question: str = Field(min_length=1)


class FaqQuestionResponse(BaseModel):
    id: int
    question: str
    created_at: datetime


class FaqGroupResponse(BaseModel):
    id: int
    answer: str
    questions: list[FaqQuestionResponse]


class FaqGroupListResponse(BaseModel):
    groups: list[FaqGroupResponse]


class DeleteFaqGroupResponse(BaseModel):
    deleted_count: int


class DeleteFaqQuestionResponse(BaseModel):
    id: int
    deleted: bool


class FaqKnowledgeController:
    """Expose administrative CRUD operations for the FAQ knowledge base."""

    def __init__(
        self,
        repository: FaqKnowledgeRepository,
        openai_service: OpenAIService | None = None,
    ) -> None:
        self.service = FaqKnowledgeService(repository, openai_service)
        self.router = APIRouter(prefix="/faq", tags=["faq"])
        self.router.add_api_route(
            "/knowledge-entries",
            self.create_entry,
            methods=["POST"],
            response_model=CreateFaqKnowledgeEntryResponse,
            status_code=status.HTTP_201_CREATED,
        )
        self.router.add_api_route(
            "/knowledge-entries/{entry_id}",
            self.delete_question,
            methods=["DELETE"],
            response_model=DeleteFaqQuestionResponse,
        )
        self.router.add_api_route(
            "/knowledge-groups",
            self.list_groups,
            methods=["GET"],
            response_model=FaqGroupListResponse,
        )
        self.router.add_api_route(
            "/knowledge-groups",
            self.create_group,
            methods=["POST"],
            response_model=FaqGroupResponse,
            status_code=status.HTTP_201_CREATED,
        )
        self.router.add_api_route(
            "/knowledge-groups/{group_entry_id}",
            self.update_group,
            methods=["PATCH"],
            response_model=FaqGroupResponse,
        )
        self.router.add_api_route(
            "/knowledge-groups/{group_entry_id}",
            self.delete_group,
            methods=["DELETE"],
            response_model=DeleteFaqGroupResponse,
        )
        self.router.add_api_route(
            "/knowledge-groups/{group_entry_id}/questions",
            self.add_question,
            methods=["POST"],
            response_model=FaqGroupResponse,
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
            raise self._unprocessable(exc) from exc
        except Exception as exc:
            self._raise_embedding_error(exc)

        return CreateFaqKnowledgeEntryResponse(
            id=entry.id,
            embedding_model=entry.embedding_model,
            created_at=entry.created_at,
        )

    def list_groups(
        self,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> FaqGroupListResponse:
        self._authenticate(chatbot_api_key)
        return FaqGroupListResponse(
            groups=[self._group_response(group) for group in self.service.list_groups()]
        )

    async def create_group(
        self,
        body: CreateFaqGroupRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> FaqGroupResponse:
        self._authenticate(chatbot_api_key)
        try:
            group = await self.service.create_group(
                questions=body.questions,
                answer=body.answer,
            )
        except ValueError as exc:
            raise self._unprocessable(exc) from exc
        except Exception as exc:
            self._raise_embedding_error(exc)
        return self._group_response(group)

    def update_group(
        self,
        group_entry_id: int,
        body: UpdateFaqGroupRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> FaqGroupResponse:
        self._authenticate(chatbot_api_key)
        try:
            group = self.service.update_group_answer(
                group_entry_id=group_entry_id,
                answer=body.answer,
            )
        except ValueError as exc:
            raise self._unprocessable(exc) from exc
        except FaqKnowledgeGroupNotFoundError as exc:
            raise self._not_found(exc) from exc
        return self._group_response(group)

    async def add_question(
        self,
        group_entry_id: int,
        body: AddFaqQuestionRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> FaqGroupResponse:
        self._authenticate(chatbot_api_key)
        try:
            group = await self.service.add_question(
                group_entry_id=group_entry_id,
                question=body.question,
            )
        except ValueError as exc:
            raise self._unprocessable(exc) from exc
        except FaqKnowledgeGroupNotFoundError as exc:
            raise self._not_found(exc) from exc
        except Exception as exc:
            self._raise_embedding_error(exc)
        return self._group_response(group)

    def delete_question(
        self,
        entry_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> DeleteFaqQuestionResponse:
        self._authenticate(chatbot_api_key)
        try:
            self.service.delete_question(entry_id=entry_id)
        except FaqKnowledgeEntryNotFoundError as exc:
            raise self._not_found(exc) from exc
        return DeleteFaqQuestionResponse(id=entry_id, deleted=True)

    def delete_group(
        self,
        group_entry_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> DeleteFaqGroupResponse:
        self._authenticate(chatbot_api_key)
        try:
            count = self.service.delete_group(group_entry_id=group_entry_id)
        except FaqKnowledgeGroupNotFoundError as exc:
            raise self._not_found(exc) from exc
        return DeleteFaqGroupResponse(deleted_count=count)

    @staticmethod
    def _group_response(group: FaqKnowledgeGroup) -> FaqGroupResponse:
        return FaqGroupResponse(
            id=group.id,
            answer=group.answer,
            questions=[
                FaqQuestionResponse(
                    id=entry.id,
                    question=entry.question,
                    created_at=entry.created_at,
                )
                for entry in group.questions
            ],
        )

    @staticmethod
    def _unprocessable(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    @staticmethod
    def _not_found(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    @staticmethod
    def _raise_embedding_error(exc: Exception) -> None:
        from openai import OpenAIError

        if isinstance(exc, OpenAIConfigurationError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OpenAI integration is not configured.",
            ) from exc
        if isinstance(exc, OpenAIError):
            logger.exception("Failed to generate an embedding for an FAQ entry")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to generate the FAQ embedding.",
            ) from exc
        raise exc

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
