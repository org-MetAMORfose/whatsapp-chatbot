"""AWS entry point. Importing the domain never configures AWS or the chatbot."""
import json
import logging
import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from matching.service import execute, retry_pending

_engine: Engine | None = None
logger = logging.getLogger(__name__)


def database() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ.get("MATCHING_DATABASE_URL")
        if not url:
            import boto3
            secret = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["DATABASE_SECRET_ARN"])
            url = json.loads(secret["SecretString"])["url"]
        _engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    return _engine


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if event.get("source") == "aws.events":
        results = retry_pending(database(), limit=25)
        logger.info("matching sweep completed: count=%s", len(results))
        return {"processed": len(results)}
    operation_id = event.get("operation_id")
    attempt = event.get("attempt")
    if not isinstance(operation_id, str) or type(attempt) is not int or attempt < 1:
        raise ValueError("Expected operation_id and positive attempt")
    result = execute(database(), operation_id, attempt)
    logger.info("matching completed: operation=%s status=%s", operation_id, result["status"])
    return result
