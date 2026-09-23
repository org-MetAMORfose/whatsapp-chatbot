"""Transactional matching with a durable outbox receipt; PostgreSQL only."""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from matching.domain import ALGORITHM_VERSION, rank, score_candidate

CANDIDATES = """
 SELECT c.*, p.area, p.approach, p.gender, p.minority_group,
   (SELECT count(*) FROM matching_slot s WHERE s.cycle_id=c.id) AS used
 FROM matching_cycle c JOIN professional p ON p.id=c.professional_id
 WHERE p.area=:area AND c.cancelled_at IS NULL
 AND c.starts_at <= clock_timestamp() AND c.deadline_at > clock_timestamp()
"""


def execute(engine: Engine, operation_id: str, attempt: int) -> dict[str, Any]:
    with engine.begin() as db:
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("SET LOCAL statement_timeout = '20s'"))
        item = db.execute(text("SELECT * FROM outbox WHERE id=:id FOR UPDATE"), {"id": operation_id}).mappings().one_or_none()
        if item is None:
            return {"status": "unknown_event"}
        if item["kind"] != "matching.requested":
            raise ValueError("Not a matching event")
        if item["status"] == "sent":
            return dict(item["payload"].get("result", {"status": "completed"}))
        if item["status"] != "processing" or item["attempts"] != attempt:
            return {"status": "stale_attempt"}
        patient_id = item["payload"]["patient_id"]
        patient = db.execute(text("SELECT * FROM patient WHERE id=:id FOR UPDATE"), {"id": patient_id}).mappings().one_or_none()
        result: dict[str, Any] = {"status": "patient_not_found"}
        if patient is not None:
            existing = db.execute(text("SELECT id, cycle_id FROM matching_slot WHERE patient_id=:id"), {"id": patient_id}).mappings().one_or_none()
            result = {"status": "matched", "slot_id": existing["id"], "cycle_id": existing["cycle_id"]} if existing else {"status": "no_capacity"}
            if existing is None:
                now = db.scalar(text("SELECT clock_timestamp()"))
                candidates = [dict(row) for row in db.execute(text(CANDIDATES), {"area": patient["area"]}).mappings()]
                for candidate, _ in rank(dict(patient), candidates, now):
                    # Revalidate after waiting for concurrent allocations/cycle edits.
                    db.execute(text("SELECT id FROM matching_cycle WHERE id=:id FOR UPDATE"), {"id": candidate["id"]})
                    db.execute(text("SELECT id FROM professional WHERE id=:id FOR SHARE"), {"id": candidate["professional_id"]})
                    fresh = db.execute(text(CANDIDATES + " AND c.id=:id"), {"area": patient["area"], "id": candidate["id"]}).mappings().one_or_none()
                    if fresh is None:
                        continue
                    score = score_candidate(dict(patient), dict(fresh), db.scalar(text("SELECT clock_timestamp()")))
                    if score is None:
                        continue
                    breakdown = {**score.breakdown, "operation_id": operation_id}
                    slot_id = db.scalar(text("""
                      INSERT INTO matching_slot (cycle_id,patient_id,compatibility_score,urgency_score,final_score,
                        score_breakdown,algorithm_version,created_at)
                      VALUES (:cycle,:patient,:compatibility,:urgency,:final,CAST(:breakdown AS jsonb),:version,clock_timestamp()) RETURNING id
                    """), {"cycle": candidate["id"], "patient": patient_id, "compatibility": score.compatibility,
                           "urgency": score.urgency, "final": score.final, "breakdown": json.dumps(breakdown), "version": ALGORITHM_VERSION})
                    result = {"status": "matched", "slot_id": slot_id, "cycle_id": candidate["id"]}
                    break
        payload = {**item["payload"], "result": result}
        db.execute(text("UPDATE outbox SET status='sent',locked_until=NULL,last_error=NULL,payload=CAST(:payload AS jsonb) WHERE id=:id"),
                   {"id": operation_id, "payload": json.dumps(payload)})
        return result


def retry_pending(engine: Engine, limit: int = 100) -> list[dict[str, Any]]:
    """Hourly reevaluation, fairly rotating unmatched registrations; no new cycles."""
    with engine.begin() as db:
        patients = db.execute(text("""
          SELECT p.id FROM patient p
          WHERE p.area IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matching_slot s WHERE s.patient_id=p.id)
            AND NOT EXISTS (SELECT 1 FROM outbox o WHERE o.kind='matching.requested'
              AND o.payload->>'patient_id'=p.id::text AND o.status IN ('pending','processing'))
          ORDER BY (SELECT max(o.created_at) FROM outbox o WHERE o.kind='matching.requested'
                    AND o.payload->>'patient_id'=p.id::text) ASC NULLS FIRST, p.created_at, p.id LIMIT :limit
        """), {"limit": limit}).scalars().all()
        bucket = db.scalar(text("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYYMMDDHH24')"))
        operations = []
        for patient_id in patients:
            operation_id = f"matching:retry:{patient_id}:{bucket}"
            inserted = db.scalar(text("""
              INSERT INTO outbox (id,kind,payload,status,available_at,attempts,locked_until,created_at)
              VALUES (:id,'matching.requested',CAST(:payload AS jsonb),'processing',clock_timestamp(),1,
                clock_timestamp()+interval '5 minutes',clock_timestamp()) ON CONFLICT DO NOTHING RETURNING id
            """), {"id": operation_id, "payload": json.dumps({"patient_id": patient_id, "source": "schedule"})})
            if inserted:
                operations.append(operation_id)
    return [execute(engine, operation_id, 1) for operation_id in operations]
