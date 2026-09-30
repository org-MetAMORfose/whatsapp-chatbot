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
