"""Independent matching use case: patient input in, allocation and result event out."""
import json
from datetime import date
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from matching.domain import ALGORITHM_VERSION, rank, score_candidate

CANDIDATES = """
 SELECT c.*, p.area,
   (SELECT count(*) FROM matching_slot s WHERE s.cycle_id=c.id) AS used
 FROM matching_cycle c JOIN professional p ON p.id=c.professional_id
 WHERE p.area=:area AND c.cancelled_at IS NULL
 AND c.starts_at <= clock_timestamp() AND c.deadline_at > clock_timestamp()
"""


def validate_patient(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Patient must be an object")
    if "patient_id" in data:
        if set(data) != {"patient_id"} or type(data["patient_id"]) is not int or data["patient_id"] <= 0:
            raise ValueError("Send only a positive patient_id, or registration data")
        return dict(data)
    allowed = {"name", "area", "birth_date", "phone_number", "channel", "psychotherapy_approach", "professional_profile"}
    if set(data) - allowed:
        raise ValueError("Unknown patient registration field")
    for field in ("name", "area", "birth_date", "phone_number"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Registration requires {field}")
    birth_date = date.fromisoformat(data["birth_date"])
    if birth_date > date.today():
        raise ValueError("birth_date cannot be in the future")
    if data.get("channel", "WHATSAPP") not in ("WHATSAPP", "TELEGRAM"):
        raise ValueError("Unknown channel")
    for field in ("psychotherapy_approach", "professional_profile"):
        if data.get(field) is not None and not isinstance(data[field], str):
            raise ValueError(f"Invalid {field}")
    return {**data, "channel": data.get("channel", "WHATSAPP")}


def register_patient(db: Connection, data: dict[str, Any]) -> int:
    # Reuse the contact identity; each registration is a new patient request.
    db.execute(text("""
      INSERT INTO person(phone_number,channel,name,birth_date,chat_mode,created_at)
      VALUES (:phone_number,:channel,:name,:birth_date,'AUTOMATIC',clock_timestamp())
      ON CONFLICT (phone_number,channel) DO NOTHING
    """), data)
    person_id = db.scalar(text("SELECT id FROM person WHERE phone_number=:phone_number AND channel=:channel FOR UPDATE"), data)
    return int(db.scalar(text("""
      INSERT INTO patient(person_id,area,psychotherapy_approach,professional_profile,created_at)
      VALUES (:person_id,:area,:approach,:profile,clock_timestamp()) RETURNING id
    """), {"person_id": person_id, "area": data["area"], "approach": data.get("psychotherapy_approach"),
           "profile": data.get("professional_profile")}))


def allocate(db: Connection, patient: dict[str, Any]) -> dict[str, Any]:
    existing = db.execute(text("SELECT id, cycle_id FROM matching_slot WHERE patient_id=:id"), {"id": patient["id"]}).mappings().one_or_none()
    if existing:
        return {"status": "matched", "slot_id": existing["id"], "cycle_id": existing["cycle_id"]}
    candidates = [dict(row) for row in db.execute(text(CANDIDATES), {"area": patient["area"]}).mappings()]
    for candidate, _ in rank(patient, candidates, db.scalar(text("SELECT clock_timestamp()"))):
        # All allocators lock the cycle before checking its current capacity.
        db.execute(text("SELECT id FROM matching_cycle WHERE id=:id FOR UPDATE"), {"id": candidate["id"]})
        db.execute(text("SELECT id FROM professional WHERE id=:id FOR SHARE"), {"id": candidate["professional_id"]})
        fresh = db.execute(text(CANDIDATES + " AND c.id=:id"), {"area": patient["area"], "id": candidate["id"]}).mappings().one_or_none()
        if fresh is None:
            continue
        score = score_candidate(patient, dict(fresh), db.scalar(text("SELECT clock_timestamp()")))
        if score is None:
            continue
        slot_id = db.scalar(text("""
          INSERT INTO matching_slot (cycle_id,patient_id,compatibility_score,urgency_score,final_score,
            score_breakdown,algorithm_version,created_at)
          VALUES (:cycle,:patient,:compatibility,:urgency,:final,CAST(:breakdown AS jsonb),:version,clock_timestamp()) RETURNING id
        """), {"cycle": candidate["id"], "patient": patient["id"], "compatibility": score.compatibility,
               "urgency": score.urgency, "final": score.final, "breakdown": json.dumps(score.breakdown), "version": ALGORITHM_VERSION})
        return {"status": "matched", "slot_id": slot_id, "cycle_id": candidate["id"]}
    return {"status": "no_capacity"}


def execute(engine: Engine, data: dict[str, Any]) -> dict[str, Any]:
    data = validate_patient(data)
    with engine.begin() as db:
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '20s'"))
        patient_id = data["patient_id"] if "patient_id" in data else register_patient(db, data)
        patient = db.execute(text("SELECT * FROM patient WHERE id=:id FOR UPDATE"), {"id": patient_id}).mappings().one_or_none()
        result = {"patient_id": patient_id, **(allocate(db, dict(patient)) if patient else {"status": "patient_not_found"})}
        # Output only: no outbox reads, claims, leases or request receipts in Lambda.
        db.execute(text("""
          INSERT INTO outbox(id,kind,payload,status,attempts,available_at,created_at)
          VALUES (:id,'matching.completed',CAST(:payload AS jsonb),'pending',0,clock_timestamp(),clock_timestamp())
        """), {"id": f"matching:result:{uuid4()}", "payload": json.dumps(result)})
        return result


def match_pending(engine: Engine, limit: int = 100) -> list[dict[str, Any]]:
    """Hourly sweep of up to 100 unmatched patients with potentially available capacity."""
    with engine.connect() as db:
        patients = db.execute(text("""
          SELECT p.id FROM patient p
          WHERE NOT EXISTS (SELECT 1 FROM matching_slot s WHERE s.patient_id=p.id)
            AND EXISTS (SELECT 1 FROM matching_cycle c JOIN professional pr ON pr.id=c.professional_id
              WHERE pr.area=p.area AND c.cancelled_at IS NULL AND c.starts_at <= clock_timestamp()
                AND c.deadline_at > clock_timestamp()
                AND (SELECT count(*) FROM matching_slot s WHERE s.cycle_id=c.id) < c.promised_patients)
          ORDER BY p.created_at, p.id LIMIT :limit
        """), {"limit": min(100, max(0, limit))}).scalars().all()
    return [execute(engine, {"patient_id": patient_id}) for patient_id in patients]
