"""PostgreSQL coverage for JSONB requirements and notifications."""

import json

from sqlalchemy import text

from tests.matching.test_postgres import database, execute, migrated_engine, seed  # noqa: F401


def _profile(*, areas: list[str], approaches: list[str]) -> str:
    return json.dumps({
        "schema_version": 1,
        "areas": areas,
        "psychotherapy": {"approaches": approaches, "specialties": []},
        "profile": {"gender": None, "race": None, "lgbtqiapn_plus": None},
    })


def _request(*, area: str, approach: str | None = None) -> str:
    return json.dumps({
        "schema_version": 1,
        "area": area,
        "psychotherapy": {"approach": approach, "specialties": []},
        "professional_preferences": {"gender": None, "race": None, "lgbtqiapn_plus": None},
    })


def test_multi_area_matches_and_snapshots_requested_area(database):  # noqa: F811
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("UPDATE professional SET matching_profile=CAST(:profile AS jsonb) WHERE id=1"),
                   {"profile": _profile(areas=["Psicoterapia", "Psiquiatria"], approaches=[])})
        db.execute(text("UPDATE patient SET area='Psiquiatria', matching_request=CAST(:request AS jsonb) WHERE id=1"),
                   {"request": _request(area="Psiquiatria")})
    result = execute(database, {"patient_id": 1})
    assert result["status"] == "matched"
    assert result["patient_area"] == "Psiquiatria"
    assert result["professional_area"] == "Psiquiatria"


def test_specific_approach_rejects_unspecified_professional(database):  # noqa: F811
    seed(database, patients=2, capacity=2)
    with database.begin() as db:
        db.execute(text("UPDATE professional SET matching_profile=CAST(:profile AS jsonb) WHERE id=1"),
                   {"profile": _profile(areas=["Psicoterapia"], approaches=[])})
        db.execute(text("UPDATE patient SET matching_request=CAST(:request AS jsonb) WHERE id=1"),
                   {"request": _request(area="Psicoterapia", approach="TCC")})
    assert execute(database, {"patient_id": 1})["status"] == "no_capacity"
    assert execute(database, {"patient_id": 2})["status"] == "matched"
    with database.begin() as db:
        db.execute(text("UPDATE professional SET matching_profile=CAST(:profile AS jsonb) WHERE id=1"),
                   {"profile": _profile(areas=["Psicoterapia"], approaches=["TCC"])})
    assert execute(database, {"patient_id": 1})["status"] == "matched"
