"""IMMEDIATE_TEST_PHONES: while set, immediate care only opens for these WhatsApp numbers (test in production).

Any format is accepted ("+55 (11) 95804-8414", "11958048414"; without "+", a number with DDD is taken as Brazilian).
WhatsApp still sends some older mobiles without the ninth digit ("551158048414"), so numbers are compared by a key
without it.
"""
from __future__ import annotations

import re


def phone_key(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if not raw.strip().startswith("+") and len(digits) in (10, 11):
        digits = "55" + digits
    if len(digits) == 13 and digits.startswith("55") and digits[4] == "9":
        digits = digits[:4] + digits[5:]
    return digits


def parse_test_phones(raw: str) -> frozenset[str]:
    return frozenset(key for item in re.split(r"[,;]", raw) if (key := phone_key(item)))
