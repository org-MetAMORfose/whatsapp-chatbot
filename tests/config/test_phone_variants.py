from app.domain.phone_variants import brazilian_phone_variants


def test_brazilian_mobile_gets_the_other_ninth_digit_form() -> None:
    assert brazilian_phone_variants("553199799197") == ["553199799197", "5531999799197"]
    assert brazilian_phone_variants("5531999799197") == ["5531999799197", "553199799197"]


def test_landlines_and_foreign_numbers_have_no_variant() -> None:
    assert brazilian_phone_variants("553133334444") == ["553133334444"]
    assert brazilian_phone_variants("15551650753") == ["15551650753"]
    assert brazilian_phone_variants("") == [""]
