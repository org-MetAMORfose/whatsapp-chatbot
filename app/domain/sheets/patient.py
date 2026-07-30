"""Patient records stored in Google Sheets."""

from typing import Any, Self

from pydantic import BaseModel, field_validator, model_validator


def _string_at(row: list[Any], index: int) -> str:
    if index >= len(row):
        return ""
    value = row[index]
    return "" if value is None else str(value).strip()


class PatientSheet(BaseModel):
    """Represents a patient row in the patients spreadsheet."""

    name: str
    phone: str
    area: str

    @field_validator("name", "phone", "area", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> str:
        return "" if value is None else str(value).strip()

    @model_validator(mode="after")
    def reject_empty_record(self) -> Self:
        if not any([self.name, self.phone, self.area]):
            raise ValueError("Patient sheet record cannot be completely empty.")
        return self

    @classmethod
    def from_sheet_row(cls, row: list[Any]) -> Self:
        return cls(
            name=_string_at(row, 1),
            phone=_string_at(row, 3),
            area=_string_at(row, 4),
        )

    def to_sheet_row(self) -> list[str]:
        return ["", self.name, "", self.phone, self.area]
