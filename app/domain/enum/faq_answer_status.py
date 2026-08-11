"""Answer status values for a FAQ interaction."""

from enum import Enum


class FaqAnswerStatus(str, Enum):
    """Represents the result observed for a FAQ interaction."""

    SATISFIED = "SATISFIED"
    NOT_FOUND = "NOT_FOUND"
    NOT_SATISFIED = "NOT_SATISFIED"
