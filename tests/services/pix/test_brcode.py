from app.services.pix import brcode

BACEN_EXAMPLE = (
    "00020126580014br.gov.bcb.pix0136123e4567-e12b-12d1-a456-4266554400005204000053039865802BR5913Fulano de Tal6008BRASILIA62070503***6304"
)


def reference_crc16(payload: str) -> str:
    """CRC-16/CCITT-FALSE written independently of the implementation under test."""
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def test_crc16_matches_bacen_example_and_reference():
    assert brcode.crc16(BACEN_EXAMPLE) == "1D3D"
    assert brcode.crc16(BACEN_EXAMPLE) == reference_crc16(BACEN_EXAMPLE)


def test_from_location_builds_dynamic_payload():
    payload = brcode.from_location(location="pix.example.com/qr/v2/abc123", merchant_name="METAMORFOSE", merchant_city="SAO PAULO")
    assert payload.startswith("000201010212")
    assert "26500014br.gov.bcb.pix2528pix.example.com/qr/v2/abc123" in payload
    assert "52040000" in payload
    assert "5303986" in payload
    assert "5802BR" in payload
    assert "5911METAMORFOSE" in payload
    assert "6009SAO PAULO" in payload
    assert "62070503***" in payload
    assert payload[-8:-4] == "6304"
    assert payload[-4:] == brcode.crc16(payload[:-4])


def test_from_location_truncates_name_and_city_and_strips_scheme():
    payload = brcode.from_location(location="https://pix.example.com/qr/v2/abc", merchant_name="A" * 30, merchant_city="B" * 20)
    assert "2525pix.example.com/qr/v2/abc" in payload
    assert "5925" + "A" * 25 in payload
    assert "6015" + "B" * 15 in payload
