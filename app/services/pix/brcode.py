"""BR Code (EMV "copia e cola") for a dynamic Pix charge, built from the charge location."""
import re
import unicodedata

MAX_NAME = 25
MAX_CITY = 15


def crc16(payload: str) -> str:
    """CRC-16/CCITT-FALSE as required by the Pix BR Code, uppercase hex."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _field(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"BR Code field {tag} is longer than 99 characters")
    return f"{tag}{len(value):02d}{value}"


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    return "".join(character for character in normalized if not unicodedata.combining(character) and character.isascii())


def from_location(*, location: str, merchant_name: str, merchant_city: str, txid: str = "***") -> str:
    url = re.sub(r"^https?://", "", location.strip())
    account = _field("00", "br.gov.bcb.pix") + _field("25", url)
    payload = (
        _field("00", "01")
        + _field("01", "12")
        + _field("26", account)
        + _field("52", "0000")
        + _field("53", "986")
        + _field("58", "BR")
        + _field("59", _ascii(merchant_name)[:MAX_NAME])
        + _field("60", _ascii(merchant_city)[:MAX_CITY])
        + _field("62", _field("05", txid))
        + "6304"
    )
    return payload + crc16(payload)
