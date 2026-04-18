"""Defines the ProfessionalStatus enum."""

from enum import Enum


class ProfessionalStatus(str, Enum):
    """Lifecycle status of a professional registration."""

    REGISTER_PENDING = "register_pending"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAYMENT_PENDING = "payment_pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
