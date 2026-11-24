"""Shared API-key check for management endpoints (header X-Chatbot-Api-Key)."""
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status

import app.config.settings as config

ApiKeyHeader = Annotated[str | None, Header(alias="X-Chatbot-Api-Key")]


def require_chatbot_api_key(provided_key: str | None) -> None:
    expected_key = config.CHATBOT_API_KEY
    if not expected_key:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Chatbot API authentication is not configured.")
    if provided_key is None or not secrets.compare_digest(provided_key.encode(), expected_key.encode()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid chatbot API key.")
