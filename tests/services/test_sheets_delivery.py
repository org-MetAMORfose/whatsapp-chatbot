from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
import requests

from app.services.google_sheets_service import GoogleSheetsAPIError, GoogleSheetsService, SpreadsheetRef


def service() -> GoogleSheetsService:
    instance = object.__new__(GoogleSheetsService)
    instance._client = MagicMock()
    instance._patients = SpreadsheetRef("sheet", 0, "Patients")
    return instance


def test_retry_updates_row_identified_by_operation_id() -> None:
    sheets = service()
    sheets._client.request.return_value.json.return_value = {"values": [["header"], ["registration:123"]]}
    payload = {"name": "Ana", "phone": "5511999999999", "area": "Psicoterapia", "birth_date": ""}
    sheets.deliver("registration:123", "sheets.patient.upsert.v1", payload)
    sheets.deliver("registration:123", "sheets.patient.upsert.v1", payload)
    writes = [call for call in sheets._client.request.call_args_list if call.args[0] == "PUT"]
    assert len(writes) == 2
    for call in writes:
        assert unquote(call.args[1]).endswith("'Patients'!A2:G2")
        assert call.kwargs["json"]["values"][0][-1] == "registration:123"
        assert call.kwargs["timeout"] == 30


def test_new_delivery_appends_after_existing_rows() -> None:
    sheets = service()
    sheets._client.request.return_value.json.side_effect = [{"values": []}, {"values": [["header"], ["old row"]]}, {}]
    sheets.deliver("new", "sheets.patient.upsert.v1", {"name": "Ana", "phone": "123", "area": "Psi", "birth_date": ""})
    assert unquote(sheets._client.request.call_args.args[1]).endswith("'Patients'!A3:G3")


def test_http_failure_propagates_for_outbox_retry() -> None:
    sheets = service()
    sheets._client.request.side_effect = requests.Timeout()
    with pytest.raises(GoogleSheetsAPIError):
        sheets.deliver("new", "sheets.patient.upsert.v1", {"name": "Ana", "phone": "123", "area": "Psi", "birth_date": ""})
