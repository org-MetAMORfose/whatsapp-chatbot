"""Run against a disposable PostgreSQL: MATCHING_TEST_DATABASE_URL only."""
import json
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

from matching.service import execute, retry_pending


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
            db.execute(text("""INSERT INTO outbox(id,kind,payload,status,attempts,available_at,locked_until,created_at)
                VALUES (:id,'matching.requested',CAST(:payload AS jsonb),'processing',1,now(),now()+interval '5 minutes',now())"""),
                       {"id": f"event-{i}", "payload": json.dumps({"patient_id": patient})})


def test_last_slot_concurrent_and_idempotent(database):
    seed(database)
    barrier = Barrier(2)

    def run(i):
        barrier.wait()
        return execute(database, f"event-{i}", 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(r["status"] for r in results) == ["matched", "no_capacity"]
    for i in range(2):
        assert execute(database, f"event-{i}", 1) == results[i]
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 1
        assert db.scalar(text("SELECT count(*) FROM outbox WHERE status='sent'")) == 2


def test_same_patient_different_events_concurrently(database):
    seed(database, patients=1, cycles=2)
    with database.begin() as db:
        db.execute(text("""INSERT INTO outbox SELECT 'duplicate',kind,payload,status,available_at,attempts,locked_until,last_error,created_at
            FROM outbox WHERE id='event-0'"""))
    barrier = Barrier(2)

    def run(event):
        barrier.wait()
        return execute(database, event, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["event-0", "duplicate"]))
    assert results[0] == results[1]
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 1


def test_pending_patient_matched_after_new_capacity(database):
    seed(database)
    assert execute(database, "event-0", 1)["status"] == "matched"
    assert execute(database, "event-1", 1)["status"] == "no_capacity"
    with database.begin() as db:
        db.execute(text("""INSERT INTO matching_cycle(professional_id,type,promised_patients,starts_at,deadline_at,created_at)
            VALUES (1,'REPLACEMENT',1,now(),now()+interval '1 day',now())"""))
    assert retry_pending(database)[0]["status"] == "matched"
    assert retry_pending(database) == []


def test_stale_attempt_and_expired_cycle(database):
    seed(database, patients=1)
    assert execute(database, "event-0", 2)["status"] == "stale_attempt"
    with database.begin() as db:
        db.execute(text("UPDATE matching_cycle SET deadline_at=now()-interval '1 second'"))
    assert execute(database, "event-0", 1)["status"] == "no_capacity"


def test_database_rejects_direct_overbooking_and_capacity_reduction(database):
    seed(database)
    execute(database, "event-0", 1)
    with pytest.raises(DBAPIError), database.begin() as db:
        db.execute(text("""INSERT INTO matching_slot(cycle_id,patient_id,compatibility_score,urgency_score,final_score,
            score_breakdown,algorithm_version,created_at) VALUES (1,2,0,0,0,'{}','test',now())"""))
    with pytest.raises(DBAPIError), database.begin() as db:
        db.execute(text("UPDATE matching_cycle SET promised_patients=0"))
    with pytest.raises(DBAPIError), database.begin() as db:
        db.execute(text("DELETE FROM matching_slot"))


def test_atomic_rollback_on_insert_failure(database):
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("ALTER TABLE matching_slot ADD CONSTRAINT fail_insert CHECK (final_score < 0)"))
    try:
        with pytest.raises(DBAPIError):
            execute(database, "event-0", 1)
        with database.connect() as db:
            assert db.scalar(text("SELECT status FROM outbox WHERE id='event-0'")) == "processing"
            assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 0
    finally:
        with database.begin() as db:
            db.execute(text("ALTER TABLE matching_slot DROP CONSTRAINT fail_insert"))
    assert execute(database, "event-0", 1)["status"] == "matched"


def test_relay_claims_separate_kinds_and_fences_expired_attempt(database):
    from sqlalchemy.orm import sessionmaker

    from app.repository.sql.outbox_repository import OutboxRepository
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("UPDATE outbox SET locked_until=now()-interval '1 second'"))
        db.execute(text("""INSERT INTO outbox(id,kind,payload,status,attempts,available_at,created_at)
            VALUES ('sheet','sheets.patient','{}','pending',0,now(),now())"""))
    repository = OutboxRepository(sessionmaker(database, expire_on_commit=False))
    sheet = repository.claim()
    assert sheet is not None
    assert sheet.id == "sheet"
    event = repository.claim(matching=True)
    assert event is not None
    assert event.id == "event-0"
    assert event.attempts == 2
    assert execute(database, event.id, 1)["status"] == "stale_attempt"
    assert execute(database, event.id, 2)["status"] == "matched"
    with database.begin() as db:
        db.execute(text("UPDATE outbox SET status='processing', attempts=5, locked_until=now()-interval '1 second' WHERE id='event-0'"))
    assert repository.claim(matching=True) is None
    with database.connect() as db:
        assert db.scalar(text("SELECT status FROM outbox WHERE id='event-0'")) == "failed"


def test_direct_write_rejects_wrong_area(database):
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("UPDATE patient SET area='Psicanálise'"))
    with pytest.raises(DBAPIError), database.begin() as db:
        db.execute(text("""INSERT INTO matching_slot(cycle_id,patient_id,compatibility_score,urgency_score,final_score,
            score_breakdown,algorithm_version,created_at) VALUES (1,1,0,0,0,'{}','test',now())"""))
    assert execute(database, "event-0", 1)["status"] == "no_capacity"
