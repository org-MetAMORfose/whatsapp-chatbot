from unittest.mock import MagicMock

import pytest
import requests

from app.services.google_sheets_service import GoogleSheetsAPIError, GoogleSheetsService, SpreadsheetRef


def service() -> GoogleSheetsService:
    instance = object.__new__(GoogleSheetsService)
    instance._client = MagicMock()
    instance._patients = SpreadsheetRef("sheet", 0, "Patients")
    return instance


def test_retry_uses_metadata_without_writing_again() -> None:
    sheets = service()
    sheets._client.request.return_value.json.return_value = {"matchedDeveloperMetadata": [{"developerMetadata": {"metadataId": 123}}]}
    sheets.deliver("registration:123", "sheets.patient.upsert.v1", {"name": "Ana", "phone": "123", "area": "Psi", "birth_date": ""})
    sheets._client.request.assert_called_once()
    assert sheets._client.request.call_args.args[1].endswith("/developerMetadata:search")


def test_values_and_metadata_are_written_atomically_without_column_g() -> None:
    sheets = service()
    sheets._client.request.return_value.json.side_effect = [{}, {"values": [["header"], ["old row"]]}, {}]
    sheets.deliver("new", "sheets.patient.upsert.v1", {"name": "Ana", "phone": "123", "area": "Psi", "birth_date": ""})
    call = sheets._client.request.call_args
    assert call.args[1].endswith(":batchUpdate")
    batch = call.kwargs["json"]["requests"]
    assert len(batch[1]["updateCells"]["rows"][0]["values"]) == 6
    assert batch[1]["updateCells"]["start"]["rowIndex"] == 2
    assert batch[2]["createDeveloperMetadata"]["developerMetadata"]["metadataValue"]


def test_http_failure_propagates_for_outbox_retry() -> None:
    sheets = service()
    sheets._client.request.side_effect = requests.Timeout()
    with pytest.raises(GoogleSheetsAPIError):
        sheets.deliver("new", "sheets.patient.upsert.v1", {"name": "Ana", "phone": "123", "area": "Psi", "birth_date": ""})
