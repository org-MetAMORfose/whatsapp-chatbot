"""Lifecycle of an immediate care request."""
from enum import Enum


class ImmediateStatus(str, Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    QUEUED = "queued"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
