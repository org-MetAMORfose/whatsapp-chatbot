"""Durations and prices of immediate care, from IMMEDIATE_PRICES: "minutes:cents" pairs separated by commas.

The flow node `imediato_duracao` has one button per duration ("20 minutos"); this setting gives each one its price,
so a price changes with a deploy and no flow edit. A new duration needs both: the button and its price here.
"""
from __future__ import annotations

import re

DEFAULT_IMMEDIATE_PRICES = "10:3000,20:5000,40:10000,60:15000"
MAX_MINUTES = 240
_NUMBER = re.compile(r"\b(\d{1,3})\b")


def parse_prices(raw: str) -> dict[int, int]:
    """Minutes -> cents, in the order given; {} when anything is malformed.

    An empty result keeps immediate care closed (app.services.immediate_care_config) instead of charging a value
    that came out of a typo.
    """
    prices: dict[int, int] = {}
    for item in raw.split(","):
        minutes_text, separator, cents_text = item.partition(":")
        minutes_text, cents_text = minutes_text.strip(), cents_text.strip()
        if not separator or not minutes_text.isdigit() or not cents_text.isdigit():
            return {}
        minutes, cents = int(minutes_text), int(cents_text)
        if not 1 <= minutes <= MAX_MINUTES or cents <= 0 or minutes in prices:
            return {}
        prices[minutes] = cents
    return prices


def duration_from_text(content: str | None, prices: dict[int, int]) -> int | None:
    """The duration of the option the patient chose ("20 minutos" -> 20), or None when it has no price."""
    for match in _NUMBER.finditer(content or ""):
        minutes = int(match.group(1))
        if minutes in prices:
            return minutes
    return None
