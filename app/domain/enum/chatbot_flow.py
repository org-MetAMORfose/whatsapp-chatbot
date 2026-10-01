"""Database-backed chatbot flow enum values."""

from enum import Enum


class NodeType(str, Enum):
    START = "START"
    MESSAGE = "MESSAGE"
    END = "END"


class InputType(str, Enum):
    TEXT = "TEXT"
    EMAIL = "EMAIL"
    DATE = "DATE"
    NUMBER = "NUMBER"
    IMAGE = "IMAGE"
    DOCUMENT = "DOCUMENT"
    VIDEO = "VIDEO"
    AUTO = "AUTO"


class RevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISCARDED = "DISCARDED"


class ChangeEntityType(str, Enum):
    NODE = "NODE"
    TRANSITION = "TRANSITION"
    TRANSITION_ACTION = "TRANSITION_ACTION"
    INPUT_ERROR_MESSAGE = "INPUT_ERROR_MESSAGE"


class ChangeOperation(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
