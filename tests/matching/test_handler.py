from unittest.mock import patch

import pytest

from matching.handler import handler


@pytest.mark.parametrize("event", [{}, {"patient_id": 1}, {"operation_id": "a", "attempt": True}, {"operation_id": "a", "attempt": 0}])
def test_rejects_untrusted_event_shape(event):
    with pytest.raises(ValueError):
        handler(event, None)


def test_handler_delegates_and_does_not_copy_patient_payload():
    with patch("matching.handler.database") as database, patch("matching.handler.execute") as execute:
        execute.return_value = {"status": "matched"}
        assert handler({"operation_id": "event-1", "attempt": 2, "patient_id": 999}, None) == {"status": "matched"}
        execute.assert_called_once_with(database.return_value, "event-1", 2)
