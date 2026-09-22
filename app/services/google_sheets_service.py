"""Small authenticated REST client for Sheets; no discovery resource graphs."""
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from app.config import settings
from app.domain.sheets import PatientSheet, ProfessionalSheet
from app.domain.sheets.professional import normalize_phone

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
BASE_URL = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleSheetsServiceError(Exception):
    """Base integration error."""


class InvalidSpreadsheetUrlError(GoogleSheetsServiceError):
    pass


class SheetTabNotFoundError(GoogleSheetsServiceError):
    pass


class GoogleSheetsCredentialsError(GoogleSheetsServiceError):
    pass


class ProfessionalNotFoundError(GoogleSheetsServiceError):
    pass


class GoogleSheetsAPIError(GoogleSheetsServiceError):
    pass


@dataclass(frozen=True)
class SpreadsheetRef:
    spreadsheet_id: str
    gid: int
    sheet_title: str


class GoogleSheetsService:
    def __init__(self, client: Any | None = None, credentials_info: dict[str, Any] | None = None,
                 patients_spreadsheet_url: str | None = None, professionals_spreadsheet_url: str | None = None) -> None:
        self._client = client if client is not None else self._build_client(credentials_info)
        self._patients = self._resolve_spreadsheet(patients_spreadsheet_url or settings.GOOGLE_PATIENTS_SPREADSHEET_URL)
        self._professionals = self._resolve_spreadsheet(professionals_spreadsheet_url or settings.GOOGLE_PROFESSIONALS_SPREADSHEET_URL)

    def _build_client(self, info: dict[str, Any] | None) -> Any:
        try:
            credentials = Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
                info or settings.load_google_service_account_credentials(), scopes=[SHEETS_SCOPE],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleSheetsCredentialsError("Invalid Google credentials") from exc
        return AuthorizedSession(credentials, refresh_timeout=30)  # type: ignore[no-untyped-call]

    def _request(self, method: str, path: str, *, params: dict[str, str] | None = None,
                 body: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.request(method, f"{BASE_URL}/{path}", params=params, json=body, timeout=30)
            response.raise_for_status()
            result: object = response.json()
        except (requests.RequestException, GoogleAuthError, ValueError) as exc:
            raise GoogleSheetsAPIError("Google Sheets request failed") from exc
        if not isinstance(result, dict):
            raise GoogleSheetsAPIError("Invalid Google Sheets response")
        return result

    def _resolve_spreadsheet(self, url: str) -> SpreadsheetRef:
        spreadsheet_id, gid = self._parse_spreadsheet_url(url)
        metadata = self._request("GET", spreadsheet_id, params={"fields": "sheets.properties(sheetId,title)"})
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("sheetId") == gid and properties.get("title"):
                return SpreadsheetRef(spreadsheet_id, gid, str(properties["title"]))
        raise SheetTabNotFoundError("No spreadsheet tab matches the configured gid")

    @staticmethod
    def _path(sheet: SpreadsheetRef, coordinates: str) -> str:
        title = sheet.sheet_title.replace("'", "''")
        cell_range = f"'{title}'!{coordinates}"
        return f"{sheet.spreadsheet_id}/values/{quote(cell_range, safe='')}"

    def _read(self, sheet: SpreadsheetRef, coordinates: str) -> list[list[str]]:
        values = self._request("GET", self._path(sheet, coordinates)).get("values", [])
        if not isinstance(values, list) or any(not isinstance(row, list) for row in values):
            raise GoogleSheetsAPIError("Invalid Google Sheets values")
        return [[str(cell) for cell in row] for row in values]

    def _write(self, sheet: SpreadsheetRef, coordinates: str, rows: list[list[str]]) -> None:
        self._request("PUT", self._path(sheet, coordinates), params={"valueInputOption": "RAW"}, body={"values": rows})

    def deliver(self, operation_id: str, kind: str, payload: dict[str, Any]) -> None:
        if kind == "sheets.patient.upsert.v1":
            sheet, end, column = self._patients, "G", 6
            row = PatientSheet.model_validate(payload).to_sheet_row()
        elif kind == "sheets.professional.upsert.v1":
            sheet, end, column = self._professionals, "O", 14
            row = ProfessionalSheet.model_validate(payload).to_sheet_row()
        else:
            raise ValueError(f"Unsupported delivery kind: {kind}")
        # Read only the ID column on retries. On new entries preserve the original row layout,
        # including sheets with empty leading columns, using explicit coordinates.
        ids = self._read(sheet, f"{end}:{end}")
        row_number = next((i for i, values in enumerate(ids, 1) if values and values[0] == operation_id), None)
        if row_number is None:
            row_number = max(2, len(self._read(sheet, f"A:{end}")) + 1)
        values = (row + [""] * column)[:column] + [operation_id]
        self._write(sheet, f"A{row_number}:{end}{row_number}", [values])

    def register_patient(self, patient: PatientSheet) -> None:
        row = max(2, len(self._read(self._patients, "A:F")) + 1)
        self._write(self._patients, f"A{row}:F{row}", [patient.to_sheet_row()])

    def register_professional(self, professional: ProfessionalSheet) -> None:
        row = max(2, len(self._read(self._professionals, "A:N")) + 1)
        self._write(self._professionals, f"A{row}:N{row}", [professional.to_sheet_row()])

    def list_patients(self) -> list[PatientSheet]:
        return [PatientSheet.from_sheet_row(row) for row in self._read(self._patients, "A:F") if any(row)]

    def list_professionals(self) -> list[ProfessionalSheet]:
        return [ProfessionalSheet.from_sheet_row(row) for row in self._read(self._professionals, "A:N")[1:] if any(row)]

    def update_professional_status(self, phone: str, active: bool) -> None:
        normalized = normalize_phone(phone)
        if normalized:
            for index, row in enumerate(self._read(self._professionals, "K:K"), 1):
                if index > 1 and row and normalize_phone(row[0]) == normalized:
                    self._write(self._professionals, f"M{index}", [["1" if active else "0"]])
                    return
        raise ProfessionalNotFoundError("Professional was not found by phone")
    def _parse_spreadsheet_url(self, spreadsheet_url: str) -> tuple[str, int]:
        parsed = urlparse(spreadsheet_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise InvalidSpreadsheetUrlError("Spreadsheet URL is invalid.")

        path_parts = [part for part in parsed.path.split("/") if part]
        try:
            spreadsheet_id = path_parts[path_parts.index("d") + 1]
        except (ValueError, IndexError) as exc:
            raise InvalidSpreadsheetUrlError(
                "Spreadsheet URL does not contain a spreadsheetId."
            ) from exc

        if not spreadsheet_id:
            raise InvalidSpreadsheetUrlError(
                "Spreadsheet URL does not contain a spreadsheetId."
            )

        query_gid = parse_qs(parsed.query).get("gid", [""])[0]
        fragment_gid = parse_qs(parsed.fragment).get("gid", [""])[0]
        gid_text = query_gid or fragment_gid
        if not gid_text:
            raise InvalidSpreadsheetUrlError("Spreadsheet URL does not contain a gid.")

        try:
            gid = int(gid_text)
        except ValueError as exc:
            raise InvalidSpreadsheetUrlError("Spreadsheet URL gid is invalid.") from exc

        return spreadsheet_id, gid
