"""AWS entry point. Importing the domain never configures AWS or the chatbot."""
import logging
import os
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from matching.input import validate_patient
from matching.service import execute, match_pending

_engine: Engine | None = None
logger = logging.getLogger(__name__)


def database() -> Engine:
    global _engine
    if _engine is None:
        url = os.environ["MATCHING_DATABASE_URL"]
        _engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    return _engine


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("Expected an object")
    if event.get("source") == "aws.events":
        results = match_pending(database(), limit=100)
        return {"processed": len(results), "results": [result.as_payload() for result in results]}
    if "patients" in event:
        patients = event["patients"]
        if set(event) != {"patients"} or not isinstance(patients, list) or not 1 <= len(patients) <= 100:
            raise ValueError("Expected between 1 and 100 patients")
        inputs = [validate_patient(patient) for patient in patients]
        return {"results": [execute(database(), patient).as_payload() for patient in inputs]}
    patient = validate_patient(event)
    return execute(database(), patient).as_payload()
