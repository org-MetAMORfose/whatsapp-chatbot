"""Outcome values for a FAQ session."""

from enum import Enum


class FaqSessionOutcome(str, Enum):
    """Represents the current or final outcome of a FAQ session."""

    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    ESCALATED = "ESCALATED"
    UNKNOWN = "UNKNOWN"
