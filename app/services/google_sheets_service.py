"""Google Sheets integration service."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import ValidationError

import app.config.settings as config
from app.domain.sheets import PatientSheet, ProfessionalSheet
from app.domain.sheets.professional import normalize_phone

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class GoogleSheetsServiceError(Exception):
    """Base exception for Google Sheets service errors."""


class InvalidSpreadsheetUrlError(GoogleSheetsServiceError):
    """Raised when a spreadsheet URL cannot be parsed."""


class SheetTabNotFoundError(GoogleSheetsServiceError):
    """Raised when a gid does not match any sheet tab."""


class GoogleSheetsCredentialsError(GoogleSheetsServiceError):
    """Raised when Google credentials are missing or invalid."""


class ProfessionalNotFoundError(GoogleSheetsServiceError):
    """Raised when a professional cannot be found in the sheet."""


class GoogleSheetsAPIError(GoogleSheetsServiceError):
    """Raised when the Google Sheets API returns an error."""


@dataclass(frozen=True)
class SpreadsheetRef:
    spreadsheet_id: str
    gid: int
    sheet_title: str


class GoogleSheetsService:
    """Encapsulates access to the patients and professionals spreadsheets."""

    def __init__(
        self,
        client: Any | None = None,
        credentials_info: dict[str, Any] | None = None,
        patients_spreadsheet_url: str | None = None,
        professionals_spreadsheet_url: str | None = None,
    ) -> None:
        self._client = client or self._build_client(credentials_info)
        self._patients = self._resolve_spreadsheet(
            patients_spreadsheet_url or config.GOOGLE_PATIENTS_SPREADSHEET_URL
        )
        self._professionals = self._resolve_spreadsheet(
            professionals_spreadsheet_url or config.GOOGLE_PROFESSIONALS_SPREADSHEET_URL
        )

    def register_professional(self, professional: ProfessionalSheet) -> None:
        row_number = self._next_row_number(self._professionals, "A:M")
        self._update_values(
            self._professionals,
            f"A{row_number}:M{row_number}",
            [professional.to_sheet_row()],
        )

    def register_patient(self, patient: PatientSheet) -> None:
        row_number = self._next_row_number(self._patients, "A:E")
        self._update_values(
            self._patients,
            f"A{row_number}:E{row_number}",
            [patient.to_sheet_row()],
        )

    def update_professional_status(self, phone: str, active: bool) -> None:
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            raise ProfessionalNotFoundError("Professional was not found by phone.")

        result = self._execute(
            self._client.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._professionals.spreadsheet_id,
                range=self._range(self._professionals, "K:K"),
            ),
            "Failed to read professionals from Google Sheets.",
        )
        values = result.get("values", [])

        for row_index, row in enumerate(values, start=1):
            if row_index == 1:
                continue
            if not row:
                continue

            sheet_phone = normalize_phone(str(row[0]))
            if sheet_phone == normalized_phone:
                self._execute(
                    self._client.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self._professionals.spreadsheet_id,
                        range=self._range(self._professionals, f"M{row_index}"),
                        valueInputOption="RAW",
                        body={"values": [["1" if active else "0"]]},
                    ),
                    "Failed to update professional status in Google Sheets.",
                )
                return

        raise ProfessionalNotFoundError("Professional was not found by phone.")

    def list_professionals(self) -> list[ProfessionalSheet]:
        result = self._execute(
            self._client.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._professionals.spreadsheet_id,
                range=self._range(self._professionals, "A:M"),
            ),
            "Failed to list professionals from Google Sheets.",
        )
        rows = result.get("values", [])

        professionals: list[ProfessionalSheet] = []
        for row in rows[1:]:
            if self._is_empty_row(row):
                continue
            try:
                professionals.append(ProfessionalSheet.from_sheet_row(row))
            except ValidationError as exc:
                raise GoogleSheetsServiceError(
                    "A professional row from Google Sheets is invalid."
                ) from exc

        return professionals

    def list_patients(self) -> list[PatientSheet]:
        result = self._execute(
            self._client.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._patients.spreadsheet_id,
                range=self._range(self._patients, "A:E"),
            ),
            "Failed to list patients from Google Sheets.",
        )
        rows = result.get("values", [])

        patients: list[PatientSheet] = []
        for row in rows:
            if self._is_empty_row(row):
                continue
            try:
                patients.append(PatientSheet.from_sheet_row(row))
            except ValidationError as exc:
                raise GoogleSheetsServiceError(
                    "A patient row from Google Sheets is invalid."
                ) from exc

        return patients

    def _build_client(self, credentials_info: dict[str, Any] | None) -> Any:
        info = credentials_info or config.GOOGLE_SERVICE_ACCOUNT_CREDENTIALS
        if not info:
            raise GoogleSheetsCredentialsError(
                "Google service account credentials are not configured."
            )

        try:
            credentials = Credentials.from_service_account_info(
                info,
                scopes=[SHEETS_SCOPE],
            )  # type: ignore[no-untyped-call]
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleSheetsCredentialsError(
                "Google service account credentials are invalid."
            ) from exc

        return build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )

    def _resolve_spreadsheet(self, spreadsheet_url: str) -> SpreadsheetRef:
        spreadsheet_id, gid = self._parse_spreadsheet_url(spreadsheet_url)
        metadata = self._execute(
            self._client.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties(sheetId,title)",
            ),
            "Failed to read spreadsheet metadata from Google Sheets.",
        )

        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("sheetId") == gid:
                title = properties.get("title")
                if not title:
                    break
                return SpreadsheetRef(
                    spreadsheet_id=spreadsheet_id,
                    gid=gid,
                    sheet_title=str(title),
                )

        raise SheetTabNotFoundError(
            "No spreadsheet tab was found for the configured gid."
        )

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

    def _next_row_number(self, spreadsheet: SpreadsheetRef, columns: str) -> int:
        result = self._execute(
            self._client.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet.spreadsheet_id,
                range=self._range(spreadsheet, columns),
            ),
            "Failed to locate the next available row in Google Sheets.",
        )
        values = result.get("values", [])
        if not isinstance(values, list):
            raise GoogleSheetsAPIError(
                "Failed to locate the next available row in Google Sheets."
            )
        return len(values) + 1

    def _update_values(
        self,
        spreadsheet: SpreadsheetRef,
        coordinates: str,
        values: list[list[str]],
    ) -> None:
        self._execute(
            self._client.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet.spreadsheet_id,
                range=self._range(spreadsheet, coordinates),
                valueInputOption="RAW",
                body={"values": values},
            ),
            "Failed to write data to Google Sheets.",
        )

    def _range(self, spreadsheet: SpreadsheetRef, coordinates: str) -> str:
        return f"'{self._escape_sheet_title(spreadsheet.sheet_title)}'!{coordinates}"

    def _execute(self, request: Any, error_message: str) -> dict[str, Any]:
        try:
            result: object = request.execute()
        except HttpError as exc:
            raise GoogleSheetsAPIError(error_message) from exc

        if not isinstance(result, dict):
            raise GoogleSheetsAPIError(error_message)

        return result

    def _is_empty_row(self, row: list[Any]) -> bool:
        return not any(str(value).strip() for value in row)

    def _escape_sheet_title(self, title: str) -> str:
        return title.replace("'", "''")
