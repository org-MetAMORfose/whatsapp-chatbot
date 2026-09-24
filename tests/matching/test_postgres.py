"""Run against a disposable PostgreSQL: MATCHING_TEST_DATABASE_URL only."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from matching.service import execute, match_pending


@pytest.fixture(scope="module")
def migrated_engine():
    url = os.environ.get("MATCHING_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MATCHING_TEST_DATABASE_URL to an isolated PostgreSQL")
    from sqlalchemy.engine import make_url
    name = "matching_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(test_url, pool_size=8)
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True,  # noqa: S603
                       env={**os.environ, "DATABASE_URL": test_url, "PYTHON_DOTENV_DISABLED": "1"}, capture_output=True)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as db:
            db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def database(migrated_engine):
    with migrated_engine.begin() as db:
        db.execute(text("TRUNCATE person, outbox RESTART IDENTITY CASCADE"))
    return migrated_engine


def seed(engine: Engine, *, patients: int = 2, capacity: int = 1, cycles: int = 1) -> None:
    with engine.begin() as db:
        person = db.scalar(text("""INSERT INTO person(phone_number,channel,chat_mode,created_at)
            VALUES ('professional','WHATSAPP','AUTOMATIC',now()) RETURNING id"""))
        professional = db.scalar(text("""INSERT INTO professional(person_id,area,professional_register,register_type,created_at)
            VALUES (:person,'Psicoterapia','123','CRP',now()) RETURNING id"""), {"person": person})
        for i in range(cycles):
            db.execute(text("""INSERT INTO matching_cycle(professional_id,type,promised_patients,starts_at,deadline_at,created_at)
              VALUES (:professional,:type,:capacity,now()-interval '1 day',now()+interval '10 days',now())"""),
                       {"professional": professional, "type": "REGULAR" if i == 0 else "REPLACEMENT", "capacity": capacity})
        for i in range(patients):
            person = db.scalar(text("""INSERT INTO person(phone_number,channel,chat_mode,created_at)
                VALUES (:phone,'WHATSAPP','AUTOMATIC',now()) RETURNING id"""), {"phone": f"patient-{i}"})
            patient = db.scalar(text("INSERT INTO patient(person_id,area,created_at) VALUES (:p,'Psicoterapia',now()) RETURNING id"), {"p": person})
            assert patient is not None


def test_last_slot_concurrently(database):
    seed(database)
    barrier = Barrier(2)

    def run(i):
        barrier.wait()
        return execute(database, {"patient_id": i + 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r["status"] for r in results) == ["matched", "no_capacity"]
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 1
        assert db.scalar(text("SELECT count(*) FROM outbox WHERE kind='matching.completed' AND status='pending'")) == 2


def test_same_patient_concurrently(database):
    seed(database, patients=1, cycles=2)
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return execute(database, {"patient_id": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 1


def test_pending_patient_matched_after_new_capacity(database):
    seed(database)
    assert execute(database, {"patient_id": 1})["status"] == "matched"
    assert execute(database, {"patient_id": 2})["status"] == "no_capacity"
    with database.begin() as db:
        db.execute(text("""INSERT INTO matching_cycle(professional_id,type,promised_patients,starts_at,deadline_at,created_at)
            VALUES (1,'REPLACEMENT',1,now(),now()+interval '1 day',now())"""))
    assert match_pending(database)[0]["status"] == "matched"
    assert match_pending(database) == []


def test_expired_cycle_and_wrong_area(database):
    seed(database)
    with database.begin() as db:
        db.execute(text("UPDATE patient SET area='Psicanálise' WHERE id=1"))
    assert execute(database, {"patient_id": 1})["status"] == "no_capacity"
    with database.begin() as db:
        db.execute(text("UPDATE matching_cycle SET deadline_at=now()-interval '1 second'"))
    assert execute(database, {"patient_id": 2})["status"] == "no_capacity"


def test_atomic_rollback_on_outbox_failure(database):
    seed(database, patients=0)
    with database.begin() as db:
        db.execute(text("ALTER TABLE outbox ADD CONSTRAINT fail_insert CHECK (kind <> 'matching.completed')"))
    try:
        with pytest.raises(DBAPIError):
            execute(database, {"name": "Ana", "birth_date": "1990-01-01", "phone_number": "5511999999999", "area": "Psicoterapia"})
        with database.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM patient")) == 0
            assert db.scalar(text("SELECT count(*) FROM person")) == 1
            assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 0
    finally:
        with database.begin() as db:
            db.execute(text("ALTER TABLE outbox DROP CONSTRAINT fail_insert"))


def test_registration_reuses_person_and_can_match_by_id(database):
    seed(database, patients=0, capacity=3)
    data = {"name": "Ana", "birth_date": "1990-01-01", "phone_number": "5511999999999", "area": "Psicoterapia"}
    result = execute(database, data)
    assert result["status"] == "matched"
    assert execute(database, {"patient_id": result["patient_id"]}) == result
    second = execute(database, data)
    assert second["patient_id"] != result["patient_id"]
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM person WHERE phone_number='5511999999999'")) == 1
        assert db.scalar(text("SELECT birth_date::text FROM person WHERE phone_number='5511999999999'")) == "1990-01-01"
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 2


def test_hourly_sweep_stops_at_100(database):
    seed(database, patients=110, capacity=110)
    assert len(match_pending(database)) == 100
    assert len(match_pending(database)) == 10


def test_no_matching_triggers(database):
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname IN ('matching_slot_guard','matching_cycle_guard')")) == 0


def test_matching_result_not_claimed_by_chatbot_relays(database):
    from sqlalchemy.orm import sessionmaker

    from app.repository.sql.outbox_repository import OutboxRepository
    seed(database, patients=1)
    execute(database, {"patient_id": 1})
    repo = OutboxRepository(sessionmaker(database))
    assert repo.claim() is None
    assert repo.claim(matching=True) is None


def test_unknown_patient_emits_result(database):
    assert execute(database, {"patient_id": 999}) == {"patient_id": 999, "status": "patient_not_found"}
    with database.connect() as db:
        assert db.scalar(text("SELECT payload->>'status' FROM outbox")) == "patient_not_found"


def test_real_batch_of_ten_without_reading_outbox(database):
    from unittest.mock import patch

    from sqlalchemy import event

    from matching.handler import handler
    seed(database, patients=5, capacity=10)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(database, "before_cursor_execute", capture)
    try:
        patients = [{"patient_id": i} for i in range(1, 6)] + [
            {"name": "Ana", "birth_date": "1990-01-01", "phone_number": f"external-{i}", "area": "Psicoterapia"}
            for i in range(5)
        ]
        with patch("matching.handler.database", return_value=database):
            result = handler({"patients": patients}, None)
        assert len(result["results"]) == 10
        assert all(item["status"] == "matched" for item in result["results"])
        assert not any("outbox" in statement and "select" in statement for statement in statements)
    finally:
        event.remove(database, "before_cursor_execute", capture)
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 10
        assert db.scalar(text("SELECT count(*) FROM outbox WHERE kind='matching.completed'")) == 10
