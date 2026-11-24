"""The two forms of a Brazilian mobile number.

WhatsApp identifies most Brazilian numbers outside the São Paulo area codes without the ninth digit ("553199799197"),
while people and the panel write it ("5531999799197"). Both reach the same phone.
"""

import re


def brazilian_phone_variants(phone: str) -> list[str]:
    """The number as given, then its other form when it is a Brazilian mobile (digits only, country code included)."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return [phone, digits[:4] + digits[5:]]
    if digits.startswith("55") and len(digits) == 12 and digits[4] in "6789":
        return [phone, digits[:4] + "9" + digits[4:]]
    return [phone]
