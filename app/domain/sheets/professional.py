"""Professional records stored in Google Sheets."""

import re
from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator


def _string_at(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


def normalize_phone(value: str) -> str:
    phone = value.strip()
    phone = re.sub(r"^https?://", "", phone, flags=re.IGNORECASE)
    phone = re.sub(r"^www\.", "", phone, flags=re.IGNORECASE)
    phone = re.sub(r"^wa\.me/", "", phone, flags=re.IGNORECASE)
    phone = phone.split("?", maxsplit=1)[0]
    return re.sub(r"\D", "", phone)


def format_whatsapp_link(value: str) -> str:
    phone = normalize_phone(value)
    return f"wa.me/{phone}" if phone else ""


class ProfessionalSheet(BaseModel):
    """Represents a professional row in the professionals spreadsheet."""

    name: str
    area: str
    phone: str
    active: bool

    @field_validator("name", "area", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_phone_field(cls, value: object) -> str:
        return normalize_phone("" if value is None else str(value))

    @field_validator("active", mode="before")
    @classmethod
    def parse_active(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value

        text = "" if value is None else str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "ativo", "active"}:
            return True
        if text in {"", "0", "false", "no", "off", "inativo", "inactive"}:
            return False

        raise ValueError("Professional active status must be '1' or '0'.")

    @model_validator(mode="after")
    def reject_empty_record(self) -> Self:
        if not any([self.name, self.area, self.phone]):
            raise ValueError("Professional sheet record cannot be completely empty.")
        return self

    @classmethod
    def from_sheet_row(cls, row: list[Any]) -> Self:
        return cls(
            name=_string_at(row, 8),
            area=_string_at(row, 9),
            phone=_string_at(row, 10),
            active=cls.parse_active(_string_at(row, 12)),
        )

    def to_sheet_row(self) -> list[str]:
        return [
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            self.name,
            self.area,
            format_whatsapp_link(self.phone),
            "",
            "1" if self.active else "0",
        ]

    def whatsapp_link(self) -> str:
        return format_whatsapp_link(self.phone)
