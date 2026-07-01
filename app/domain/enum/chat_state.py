"""Defines the administrative state shown for a chat."""

from enum import Enum


class ChatState(str, Enum):
    """Reason why a conversation may need human attention."""

    AGENT_RUNNING = "agent_running"
    AGENT_STOP = "agent_stop"
    FEEDBACK = "feedback"
    QUESTION = "question"
    PROFESSIONAL_SUPPORT = "professional_support"
    NEW_PATIENT = "new_patient"
    PAYMENT_RENEWAL = "payment_renewal"
    PROFESSIONAL_REGISTRATION = "professional_registration"


CHAT_STATE_PRIORITY: dict[ChatState, int] = {
    ChatState.AGENT_RUNNING: 0,
    ChatState.AGENT_STOP: 70,
    ChatState.FEEDBACK: 10,
    ChatState.QUESTION: 20,
    ChatState.PROFESSIONAL_SUPPORT: 30,
    ChatState.NEW_PATIENT: 40,
    ChatState.PAYMENT_RENEWAL: 50,
    ChatState.PROFESSIONAL_REGISTRATION: 60,
}
