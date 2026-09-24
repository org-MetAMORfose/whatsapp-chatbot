from unittest.mock import patch

import pytest

from matching.handler import handler


@pytest.mark.parametrize("event", [{}, {"patient_id": True}, {"patient_id": 0},
    {"patient_id": 1, "name": "Ana"}, {"name": "Ana"}, {"patients": []}, {"patients": [{"patient_id": 1}] * 101},
    {"phone_number": "123", "name": "Ana", "area": "Psicoterapia", "birth_date": "invalid"}])
def test_rejects_invalid_input_before_connecting(event):
    with patch("matching.handler.database") as database, pytest.raises(ValueError):
        handler(event, None)
    database.assert_not_called()


def test_accepts_patient_id_without_outbox_event():
    with patch("matching.handler.database") as database, patch("matching.handler.execute") as execute:
        execute.return_value = {"status": "matched"}
        assert handler({"patient_id": 1}, None) == {"status": "matched"}
        execute.assert_called_once_with(database.return_value, {"patient_id": 1})


def test_batch_of_ten_patients():
    with patch("matching.handler.database"), patch("matching.handler.execute") as execute:
        execute.side_effect = [{"patient_id": i} for i in range(1, 11)]
        result = handler({"patients": [{"patient_id": i} for i in range(1, 11)]}, None)
        assert len(result["results"]) == 10
        assert execute.call_count == 10


def test_schedule_limit():
    with patch("matching.handler.database") as database, patch("matching.handler.match_pending") as sweep:
        sweep.return_value = []
        assert handler({"source": "aws.events"}, None)["processed"] == 0
        sweep.assert_called_once_with(database.return_value, limit=100)
