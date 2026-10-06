"""Administrative endpoints for durable chatbot graph drafts."""

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

import app.config.settings as config
from app.agent.action_catalog import action_catalog
from app.domain.enum.chatbot_flow import ChangeEntityType, ChangeOperation
from app.services.chatbot_flow_admin_service import (
    ChatFlowAdminService,
    DraftChangeInput,
    FlowCachePublishError,
    FlowDraftConflictError,
    FlowDraftNotFoundError,
    FlowSheetTabsUnavailableError,
    InvalidFlowChangeError,
    InvalidFlowDraftError,
)
from app.services.chatbot_flow_validation_service import FlowValidationResult


class CreateFlowDraftRequest(BaseModel):
    base_revision_id: int | None = None


class FlowChangeRequest(BaseModel):
    entity_type: ChangeEntityType
    operation: ChangeOperation
    entity_id: int | None = None
    draft_entity_id: int | None = None
    new_value: dict[str, Any] | None = None


class SaveFlowChangesRequest(BaseModel):
    changes: list[FlowChangeRequest] = Field(min_length=1)


class ChatbotFlowController:
    def __init__(self, service: ChatFlowAdminService) -> None:
        self.service = service
        self.router = APIRouter(prefix="/chatbot-flow", tags=["chatbot-flow"])
        self.router.add_api_route(
            "/actions",
            self.list_actions,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/sheets/tabs",
            self.list_sheet_tabs,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/revisions",
            self.create_draft,
            methods=["POST"],
            status_code=status.HTTP_201_CREATED,
        )
        self.router.add_api_route(
            "/revisions",
            self.list_revisions,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/revisions/{revision_id}",
            self.get_revision,
            methods=["GET"],
        )
        self.router.add_api_route(
            "/revisions/{revision_id}/changes",
            self.save_changes,
            methods=["PUT"],
        )
        self.router.add_api_route(
            "/revisions/{revision_id}/validate",
            self.validate_revision,
            methods=["POST"],
            response_model=FlowValidationResult,
        )
        self.router.add_api_route(
            "/revisions/{revision_id}/publish",
            self.publish_revision,
            methods=["POST"],
        )
        self.router.add_api_route(
            "/revisions/{revision_id}",
            self.discard_revision,
            methods=["DELETE"],
        )

    def list_actions(
        self,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        return action_catalog()

    def list_sheet_tabs(
        self,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.list_sheet_tabs()
        except FlowSheetTabsUnavailableError as exc:
            raise self._sheet_tabs_unavailable(exc) from exc

    def create_draft(
        self,
        body: CreateFlowDraftRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.create_draft(body.base_revision_id)
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc

    def list_revisions(
        self,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        return self.service.list_revisions()

    def get_revision(
        self,
        revision_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.get_graph(revision_id)
        except FlowDraftNotFoundError as exc:
            raise self._not_found(exc) from exc
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc

    def save_changes(
        self,
        revision_id: int,
        body: SaveFlowChangesRequest,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.save_changes(
                revision_id,
                [
                    DraftChangeInput(
                        entity_type=change.entity_type,
                        operation=change.operation,
                        entity_id=change.entity_id,
                        draft_entity_id=change.draft_entity_id,
                        new_value=change.new_value,
                    )
                    for change in body.changes
                ],
            )
        except FlowDraftNotFoundError as exc:
            raise self._not_found(exc) from exc
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc
        except FlowSheetTabsUnavailableError as exc:
            raise self._sheet_tabs_unavailable(exc) from exc
        except InvalidFlowChangeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_CHANGE", "message": str(exc)},
            ) from exc

    def validate_revision(
        self,
        revision_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> FlowValidationResult:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.validate(revision_id)
        except FlowDraftNotFoundError as exc:
            raise self._not_found(exc) from exc
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc
        except FlowSheetTabsUnavailableError as exc:
            raise self._sheet_tabs_unavailable(exc) from exc

    async def publish_revision(
        self,
        revision_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return await self.service.publish(revision_id)
        except FlowDraftNotFoundError as exc:
            raise self._not_found(exc) from exc
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc
        except FlowSheetTabsUnavailableError as exc:
            raise self._sheet_tabs_unavailable(exc) from exc
        except InvalidFlowDraftError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "INVALID_FLOW",
                    "message": str(exc),
                    "errors": [error.model_dump() for error in exc.result.errors],
                },
            ) from exc
        except InvalidFlowChangeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_CHANGE", "message": str(exc)},
            ) from exc
        except FlowCachePublishError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "FLOW_CACHE_PUBLISH_FAILED",
                    "message": str(exc),
                    "revision_id": exc.revision_id,
                    "version": exc.version,
                    "retryable": True,
                },
            ) from exc

    def discard_revision(
        self,
        revision_id: int,
        chatbot_api_key: Annotated[
            str | None,
            Header(alias="X-Chatbot-Api-Key"),
        ] = None,
    ) -> dict[str, Any]:
        self._authenticate(chatbot_api_key)
        try:
            return self.service.discard(revision_id)
        except FlowDraftNotFoundError as exc:
            raise self._not_found(exc) from exc
        except FlowDraftConflictError as exc:
            raise self._conflict(exc) from exc

    @staticmethod
    def _authenticate(provided_key: str | None) -> None:
        expected_key = config.CHATBOT_API_KEY
        if not expected_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chatbot API authentication is not configured.",
            )
        if provided_key is None or not secrets.compare_digest(provided_key, expected_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid chatbot API key.",
            )

    @staticmethod
    def _not_found(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "REVISION_NOT_FOUND", "message": str(exc)},
        )

    @staticmethod
    def _conflict(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "REVISION_CONFLICT", "message": str(exc)},
        )

    @staticmethod
    def _sheet_tabs_unavailable(exc: Exception) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "SHEET_TABS_UNAVAILABLE",
                "message": str(exc),
                "retryable": True,
            },
        )
