"""Exercise the JSONB backfill against a disposable PostgreSQL database."""

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def test_legacy_matching_fields_are_backfilled() -> None:
    url = os.environ.get("DELIVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DELIVERY_TEST_DATABASE_URL to an isolated PostgreSQL")
    database_name = "matching_backfill_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    test_url = make_url(url).set(database=database_name).render_as_string(hide_password=False)
    engine = create_engine(test_url)

    def upgrade(revision: str) -> None:
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", revision],
            check=True, capture_output=True,
            env={**os.environ, "DATABASE_URL": test_url.replace("%", "%%"), "PYTHON_DOTENV_DISABLED": "1"},
        )

    try:
        upgrade("0014_patient_order")
        with engine.begin() as connection:
            professional_person = connection.scalar(text("""
                INSERT INTO person(phone_number, channel, chat_mode, created_at, name)
                VALUES ('5511999999991', 'WHATSAPP', 'AUTOMATIC', now(), 'Profissional') RETURNING id
            """))
            patient_person = connection.scalar(text("""
                INSERT INTO person(phone_number, channel, chat_mode, created_at, name)
                VALUES ('5511999999992', 'WHATSAPP', 'AUTOMATIC', now(), 'Paciente') RETURNING id
            """))
            connection.execute(text("""
                INSERT INTO professional(person_id, area, professional_register, register_type,
                                         gender, minority_group, created_at)
                VALUES (:person_id, 'Psicanálise', 'LEGACY-1', 'CRP', 'Mulher', 'Negro LGBT', now())
            """), {"person_id": professional_person})
            connection.execute(text("""
                INSERT INTO patient(person_id, area, professional_profile, created_at)
                VALUES (:person_id, 'Psicanálise', 'Mulher negra', now())
            """), {"person_id": patient_person})
        upgrade("head")
        with engine.connect() as connection:
            profile = connection.scalar(text("SELECT matching_profile FROM professional"))
            request = connection.scalar(text("SELECT matching_request FROM patient"))
        assert profile["areas"] == ["Psicoterapia"]
        assert profile["psychotherapy"]["approaches"] == ["Psicanálise"]
        assert profile["profile"] == {"gender": "Mulher", "race": "Negra", "lgbtqiapn_plus": True}
        assert request["area"] == "Psicoterapia"
        assert request["psychotherapy"]["approach"] == "Psicanálise"
        assert request["professional_preferences"] == {
            "gender": "Mulher", "race": "Negra", "lgbtqiapn_plus": None,
        }
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()
