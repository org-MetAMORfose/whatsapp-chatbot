"""Translate untrusted JSON at the Lambda boundary into domain dataclasses."""
from datetime import date
from typing import Any

from app.domain.enum.channels import Channel
from app.domain.matching import PatientInput, PatientReference, PatientRegistration


def validate_patient(data: Any) -> PatientInput:
    if not isinstance(data, dict):
        raise ValueError("Patient must be an object")
    if "patient_id" in data:
        if set(data) != {"patient_id"} or type(data["patient_id"]) is not int or data["patient_id"] <= 0:
            raise ValueError("Send only a positive patient_id, or registration data")
        return PatientReference(data["patient_id"])
    allowed = {"name", "area", "birth_date", "phone_number", "channel", "psychotherapy_approach", "professional_profile"}
    if set(data) - allowed:
        raise ValueError("Unknown patient registration field")
    for field in ("name", "area", "birth_date", "phone_number"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Registration requires {field}")
    birth_date = date.fromisoformat(data["birth_date"])
    if birth_date > date.today():
        raise ValueError("birth_date cannot be in the future")
    channel = Channel(data.get("channel", "WHATSAPP"))
    for field in ("psychotherapy_approach", "professional_profile"):
        if data.get(field) is not None and not isinstance(data[field], str):
            raise ValueError(f"Invalid {field}")
    return PatientRegistration(name=data["name"], area=data["area"], birth_date=birth_date,
        phone_number=data["phone_number"], channel=channel, psychotherapy_approach=data.get("psychotherapy_approach"),
        professional_profile=data.get("professional_profile"))
