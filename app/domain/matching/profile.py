"""Canonical matching data shared by registrations, migration and Lambda."""

from __future__ import annotations

import unicodedata
from typing import Any

SCHEMA_VERSION = 1
PSYCHOTHERAPY = "Psicoterapia"
APPROACHES = ("TCC", "Psicanálise")
SPECIALTIES = (
    "Autismo",
    "TDAH",
    "Transtorno Bipolar",
    "Transtorno de Personalidade Borderline",
    "Ansiedade",
    "Depressão",
)


def key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", (value or "").strip().casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def area(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    aliases = {
        "psicoterapia": PSYCHOTHERAPY,
        "psicanalise": PSYCHOTHERAPY,
        "psicoterapia tcc": PSYCHOTHERAPY,
        "psicoterapia com mulher": PSYCHOTHERAPY,
        "psicoterapia com mulher negra": PSYCHOTHERAPY,
        "psicoterapia com homem negro": PSYCHOTHERAPY,
        "psicoterapia lgbtqiapn+": PSYCHOTHERAPY,
        "psiquiatria": "Psiquiatria",
        "clinico geral": "Clínico geral",
        "nutricao": "Nutrição",
        "nutricionista": "Nutrição",
        "terapia holistica": "Terapia holística",
    }
    return aliases.get(key(value), value.strip())


def approach(value: str | None) -> str | None:
    aliases = {"tcc": "TCC", "psicoterapia tcc": "TCC", "psicanalise": "Psicanálise"}
    return aliases.get(key(value))


def specialties(values: list[str] | None) -> list[str]:
    lookup = {key(value): value for value in SPECIALTIES}
    lookup.update({
        "bipolaridade": "Transtorno Bipolar",
        "borderline": "Transtorno de Personalidade Borderline",
    })
    result: list[str] = []
    for value in values or []:
        canonical = lookup.get(key(value))
        if canonical is None:
            raise ValueError(f"Unknown psychotherapy specialty: {value}")
        if canonical not in result:
            result.append(canonical)
    return result


def identity(gender: str | None = None, minority_group: str | None = None, *, race: str | None = None,
             lgbtqiapn_plus: bool | None = None) -> dict[str, str | bool | None]:
    group = key(minority_group)
    inferred_race = "Negra" if "negr" in group else None
    inferred_lgbt = True if "lgbt" in group else None
    normalized_gender = {"feminino": "Mulher", "masculino": "Homem"}.get(key(gender), gender)
    return {
        "gender": None if key(gender) in ("", "prefiro nao informar", "sem preferencia") else normalized_gender,
        "race": race or inferred_race,
        "lgbtqiapn_plus": lgbtqiapn_plus if lgbtqiapn_plus is not None else inferred_lgbt,
    }


def profile_preference(value: str | None) -> dict[str, str | bool | None]:
    choices: dict[str, dict[str, str | bool | None]] = {
        "mulher": {"gender": "Mulher"},
        "mulher negra": {"gender": "Mulher", "race": "Negra"},
        "homem negro": {"gender": "Homem", "race": "Negra"},
        "lgbtqiapn+": {"lgbtqiapn_plus": True},
    }
    return {"gender": None, "race": None, "lgbtqiapn_plus": None, **choices.get(key(value), {})}


def professional_profile(*, areas: list[str], approaches: list[str] | None = None,
                         focus: list[str] | None = None, gender: str | None = None,
                         minority_group: str | None = None, race: str | None = None,
                         lgbtqiapn_plus: bool | None = None) -> dict[str, Any]:
    normalized_areas = list(dict.fromkeys(filter(None, (area(value) for value in areas))))
    normalized_approaches = list(dict.fromkeys(filter(None, (approach(value) for value in approaches or []))))
    inferred_gender = gender
    inferred_race = race
    inferred_lgbt = lgbtqiapn_plus
    for value in areas:
        normalized = key(value)
        if normalized in ("psicanalise", "psicoterapia tcc"):
            identified_approach = approach(value)
            if identified_approach is not None and identified_approach not in normalized_approaches:
                normalized_approaches.append(identified_approach)
        if normalized in ("psicoterapia com mulher", "psicoterapia com mulher negra"):
            inferred_gender = inferred_gender or "Mulher"
        elif normalized == "psicoterapia com homem negro":
            inferred_gender = inferred_gender or "Homem"
        if normalized in ("psicoterapia com mulher negra", "psicoterapia com homem negro"):
            inferred_race = inferred_race or "Negra"
        if normalized == "psicoterapia lgbtqiapn+":
            inferred_lgbt = True
    return {
        "schema_version": SCHEMA_VERSION,
        "areas": normalized_areas,
        "psychotherapy": {"approaches": normalized_approaches, "specialties": specialties(focus)},
        "profile": identity(inferred_gender, minority_group, race=inferred_race, lgbtqiapn_plus=inferred_lgbt),
    }


def patient_request(*, selected_area: str | None, selected_approach: str | None = None,
                    professional_profile: str | None = None, focus: list[str] | None = None,
                    preferred_gender: str | None = None, preferred_race: str | None = None,
                    prefers_lgbtqiapn_plus: bool | None = None) -> dict[str, Any]:
    preference = profile_preference(professional_profile)
    if preferred_gender is not None:
        preference["gender"] = preferred_gender
    if preferred_race is not None:
        preference["race"] = preferred_race
    if prefers_lgbtqiapn_plus is not None:
        preference["lgbtqiapn_plus"] = prefers_lgbtqiapn_plus
    actual_approach = approach(selected_approach)
    if key(selected_area) == "psicanalise":
        actual_approach = "Psicanálise"
    selected_area_normalized = area(selected_area)
    if selected_area_normalized != PSYCHOTHERAPY:
        actual_approach = None
        focus = None
    return {
        "schema_version": SCHEMA_VERSION,
        "area": selected_area_normalized,
        "psychotherapy": {"approach": actual_approach, "specialties": specialties(focus)},
        "professional_preferences": preference,
    }


def from_legacy_professional(record: Any) -> dict[str, Any]:
    return professional_profile(areas=[part.strip() for part in record.area.split(",") if part.strip()],
                                approaches=[record.approach] if record.approach else [],
                                gender=record.gender, minority_group=record.minority_group)


def from_legacy_patient(record: Any) -> dict[str, Any]:
    return patient_request(selected_area=record.area, selected_approach=record.psychotherapy_approach,
                           professional_profile=record.professional_profile)
