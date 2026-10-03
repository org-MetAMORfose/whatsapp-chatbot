"""Run against a disposable PostgreSQL: DELIVERY_TEST_DATABASE_URL only."""

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

from matching.input import validate_patient
from matching.service import execute as execute_matching
from matching.service import match_pending


def execute(engine: Engine, data):
    return execute_matching(engine, validate_patient(data)).as_payload()


@pytest.fixture(scope="module")
def migrated_engine():
    url = os.environ.get("DELIVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DELIVERY_TEST_DATABASE_URL to an isolated PostgreSQL")
    from sqlalchemy.engine import make_url

    name = "matching_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as db:
        db.execute(text(f'CREATE DATABASE "{name}"'))
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(test_url, pool_size=8)
    try:
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": test_url.replace("%", "%%"), "PYTHON_DOTENV_DISABLED": "1"},
            capture_output=True,
        )
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
        person = db.scalar(
            text("""INSERT INTO person(phone_number,channel,chat_mode,created_at,name)
            VALUES ('5511977776666','WHATSAPP','AUTOMATIC',now(),'Dra. Ana') RETURNING id""")
        )
        professional = db.scalar(
            text("""INSERT INTO professional(person_id,area,professional_register,register_type,email,created_at)
            VALUES (:person,'Psicoterapia','123','CRP','ana@example.com',now()) RETURNING id"""),
            {"person": person},
        )
        for i in range(cycles):
            db.execute(
                text("""INSERT INTO matching_cycle(professional_id,type,promised_patients,starts_at,deadline_at,created_at)
              VALUES (:professional,:type,:capacity,now()-interval '1 day',now()+interval '10 days',now())"""),
                {"professional": professional, "type": "REGULAR" if i == 0 else "REPLACEMENT", "capacity": capacity},
            )
        for i in range(patients):
            person = db.scalar(
                text("""INSERT INTO person(phone_number,channel,chat_mode,created_at,name)
                VALUES (:phone,'WHATSAPP','AUTOMATIC',now(),:name) RETURNING id"""),
                {"phone": f"55119888{i:05d}", "name": f"Paciente {i}"},
            )
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


def test_same_patient_can_be_allocated_once_in_each_cycle(database):
    seed(database, patients=1, cycles=2)
    barrier = Barrier(2)

    def run(_):
        barrier.wait()
        return execute(database, {"patient_id": 1})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert all(result["status"] == "matched" for result in results)
    assert {result["cycle_id"] for result in results} == {1, 2}
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 2
        assert db.scalar(text("SELECT count(*) FROM matching_slot WHERE patient_id=1 AND cycle_id=1")) == 1


def test_same_patient_is_not_allocated_twice_in_one_cycle(database):
    seed(database, patients=1, capacity=2)

    assert execute(database, {"patient_id": 1})["status"] == "matched"
    assert execute(database, {"patient_id": 1})["status"] == "no_capacity"

    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 1


def test_pending_patient_matched_after_new_capacity(database):
    seed(database)
    assert execute(database, {"patient_id": 1})["status"] == "matched"
    assert execute(database, {"patient_id": 2})["status"] == "no_capacity"
    with database.begin() as db:
        db.execute(
            text("""INSERT INTO matching_cycle(professional_id,type,promised_patients,starts_at,deadline_at,created_at)
            VALUES (1,'REPLACEMENT',2,now(),now()+interval '1 day',now())""")
        )
    results = match_pending(database)
    assert len(results) == 2
    assert all(result.status == "matched" for result in results)
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
    assert execute(database, {"patient_id": result["patient_id"]}) == {
        "patient_id": result["patient_id"],
        "status": "no_capacity",
    }
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
    assert repo.claim(kinds=("sheets.patient.upsert.v1", "sheets.professional.upsert.v1")) is None
    assert repo.claim(kinds=("matching.requested",), max_attempts=1) is None


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
            {"name": "Ana", "birth_date": "1990-01-01", "phone_number": f"55119666{i:05d}", "area": "Psicoterapia"} for i in range(5)
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


def test_completed_event_captures_notification_snapshot(database):
    seed(database, patients=1)
    first = execute(database, {"patient_id": 1})
    repeated = execute(database, {"patient_id": 1})
    assert repeated == {"patient_id": 1, "status": "no_capacity"}
    assert first == {
        "status": "matched",
        "patient_id": 1,
        "slot_id": first["slot_id"],
        "cycle_id": first["cycle_id"],
        "patient_name": "Paciente 0",
        "patient_phone": "5511988800000",
        "patient_area": "Psicoterapia",
        "professional_name": "Dra. Ana",
        "professional_area": "Psicoterapia",
        "professional_phone": "5511977776666",
        "professional_email": "ana@example.com",
    }
    with database.begin() as db:
        db.execute(text("UPDATE person SET name='Changed', phone_number='changed-' || id"))
        payloads = db.execute(text("SELECT payload FROM outbox WHERE kind='matching.completed'")).scalars().all()
        professional_payloads = db.execute(text(
            "SELECT payload FROM outbox WHERE kind='matching.professional.notification'"
        )).scalars().all()
        email_payloads = db.execute(text(
            "SELECT payload FROM outbox WHERE kind='matching.professional.email'"
        )).scalars().all()
    assert payloads == [first, repeated]

    assert professional_payloads == [first]
    assert email_payloads == [first]

def test_seeded_chatbot_flow_is_complete_and_loadable(database):
    from sqlalchemy.orm import sessionmaker

    from app.domain.enum.chatbot_flow import InputType, NodeType
    from app.repository.sql.chatbot_flow_repository import ChatFlowRepository

    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM chatbot_flow.node")) == 70
        assert db.scalar(text("SELECT count(*) FROM chatbot_flow.transition")) == 157
        assert db.scalar(text("SELECT count(*) FROM chatbot_flow.transition_action")) == 172
        assert db.scalar(text("SELECT count(*) FROM chatbot_flow.input_error_message")) == 8
        assert (
            db.scalar(
                text("""
            SELECT count(*)
            FROM chatbot_flow.transition transition
            LEFT JOIN chatbot_flow.node target ON target.id = transition.next_node_id
            WHERE target.id IS NULL
        """)
            )
            == 0
        )
        assert (
            db.scalar(
                text("""
            SELECT count(*)
            FROM chatbot_flow.transition_action
            WHERE action_key LIKE 'sheets_%' AND is_required
        """)
            )
            == 0
        )
        assert (
            db.scalar(
                text("""
            SELECT count(*)
            FROM chatbot_flow.transition_action
            WHERE action_key NOT LIKE 'sheets_%' AND NOT is_required
        """)
            )
            == 0
        )

    revision, flow = ChatFlowRepository(sessionmaker(database, expire_on_commit=False)).load()

    assert revision == 1
    assert len(flow.nodes) == 70
    start = flow.get("start")
    birth_date = flow.get("paciente_data_nascimento")
    assert start is not None
    assert birth_date is not None
    assert start.type == NodeType.START
    assert (start.position_x, start.position_y) == (0, 0)
    assert birth_date.title == ("Data de nascimento do paciente")
    assert flow.input_error_messages[InputType.EMAIL].startswith("Envie um e-mail válido")


def test_incomplete_snapshot_rolls_back_allocation_and_event(database):
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("UPDATE person SET name=NULL"))
    with pytest.raises(ValueError, match="Incomplete matching notification snapshot"):
        execute(database, {"patient_id": 1})
    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 0
        assert db.scalar(text("SELECT count(*) FROM outbox")) == 0


def test_missing_professional_email_rolls_back_allocation_and_events(database):
    seed(database, patients=1)
    with database.begin() as db:
        db.execute(text("UPDATE professional SET email=NULL"))

    with pytest.raises(ValueError, match="Incomplete matching notification snapshot"):
        execute(database, {"patient_id": 1})

    with database.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM matching_slot")) == 0
        assert db.scalar(text("SELECT count(*) FROM outbox")) == 0
