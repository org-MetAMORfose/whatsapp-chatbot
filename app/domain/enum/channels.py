"""Defines the Channel enum representing messaging platforms."""

from enum import Enum


class Channel(str, Enum):
    """Enum representing the messaging platform/channel where a message originates."""

    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"
