"""Translate untrusted JSON at the Lambda boundary into domain dataclasses."""
from datetime import date
from typing import Any

from app.domain.enum.channels import Channel
from app.domain.matching import PatientInput, PatientReference, PatientRegistration
from app.domain.matching.profile import approach as normalize_approach
from app.domain.matching.profile import key, patient_request


def validate_patient(data: Any) -> PatientInput:
    if not isinstance(data, dict):
        raise ValueError("Patient must be an object")
    if "patient_id" in data:
        if set(data) != {"patient_id"} or type(data["patient_id"]) is not int or data["patient_id"] <= 0:
            raise ValueError("Send only a positive patient_id, or registration data")
        return PatientReference(data["patient_id"])
    allowed = {"name", "area", "birth_date", "phone_number", "channel", "psychotherapy_approach",
               "professional_profile", "psychotherapy_specialties", "preferred_gender", "preferred_race",
               "prefers_lgbtqiapn_plus"}
    if set(data) - allowed:
        raise ValueError("Unknown patient registration field")
    for field in ("name", "area", "birth_date", "phone_number"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Registration requires {field}")
    birth_date = date.fromisoformat(data["birth_date"])
    if birth_date > date.today():
        raise ValueError("birth_date cannot be in the future")
    channel = Channel(data.get("channel", "WHATSAPP"))
    for field in ("psychotherapy_approach", "professional_profile", "preferred_gender", "preferred_race"):
        if data.get(field) is not None and not isinstance(data[field], str):
            raise ValueError(f"Invalid {field}")
    if data.get("prefers_lgbtqiapn_plus") is not None and type(data["prefers_lgbtqiapn_plus"]) is not bool:
        raise ValueError("Invalid prefers_lgbtqiapn_plus")
    selected_approach = data.get("psychotherapy_approach")
    if selected_approach is not None and key(selected_approach) not in ("", "sem preferencia"):
        if normalize_approach(selected_approach) is None:
            raise ValueError("Unknown psychotherapy_approach")
    focuses = data.get("psychotherapy_specialties")
    if focuses is not None and (not isinstance(focuses, list) or any(not isinstance(item, str) for item in focuses)):
        raise ValueError("Invalid psychotherapy_specialties")
    request = patient_request(selected_area=data["area"], selected_approach=data.get("psychotherapy_approach"),
        professional_profile=data.get("professional_profile"), focus=focuses,
        preferred_gender=data.get("preferred_gender"), preferred_race=data.get("preferred_race"),
        prefers_lgbtqiapn_plus=data.get("prefers_lgbtqiapn_plus"))
    return PatientRegistration(name=data["name"], area=data["area"], birth_date=birth_date,
        phone_number=data["phone_number"], channel=channel, psychotherapy_approach=data.get("psychotherapy_approach"),
        professional_profile=data.get("professional_profile"), matching_request=request)
