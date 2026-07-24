"""Defines the administrative state shown for a chat."""

from enum import Enum


class ChatState(str, Enum):
    """Reason why a conversation may need human attention."""

    FEEDBACK = "feedback"
    QUESTION = "question"
    PROFESSIONAL_SUPPORT = "professional_support"
    NEW_PATIENT = "new_patient"
    RETURNING_PATIENT = "returning_patient"
    PAYMENT_RENEWAL = "payment_renewal"
    PROFESSIONAL_REGISTRATION = "professional_registration"


CHAT_STATE_PRIORITY: dict[ChatState, int] = {
    ChatState.NEW_PATIENT: 5,
    ChatState.FEEDBACK: 10,
    ChatState.QUESTION: 20,
    ChatState.PROFESSIONAL_SUPPORT: 30,
    ChatState.RETURNING_PATIENT: 40,
    ChatState.PAYMENT_RENEWAL: 50,
    ChatState.PROFESSIONAL_REGISTRATION: 60,
}
