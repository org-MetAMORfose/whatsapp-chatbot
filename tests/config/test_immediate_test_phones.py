import pytest

from app.config.immediate_test_phones import parse_test_phones, phone_key


@pytest.mark.parametrize(
    "raw",
    [
        "5511958048414",
        "+55 (11) 95804-8414",
        "11958048414",
        "(11) 95804-8414",
        # WhatsApp still sends some older mobiles without the ninth digit.
        "551158048414",
    ],
)
def test_every_way_of_writing_the_same_mobile_has_the_same_key(raw: str) -> None:
    assert phone_key(raw) == phone_key("5511958048414")


def test_different_numbers_have_different_keys() -> None:
    assert phone_key("5511958048414") != phone_key("5511958048415")
    assert phone_key("5511958048414") != phone_key("5521958048414")


def test_a_number_with_plus_keeps_its_country_code() -> None:
    assert phone_key("+1 415 555 0123") == "14155550123"


def test_parse_test_phones_accepts_commas_semicolons_and_any_format() -> None:
    assert parse_test_phones(" +55 11 95804-8414 , 21987654321;5511912345678 ") == frozenset(
        {phone_key("5511958048414"), phone_key("5521987654321"), phone_key("5511912345678")}
    )


def test_parse_test_phones_empty_means_no_list() -> None:
    assert parse_test_phones("") == frozenset()
    assert parse_test_phones(" , ") == frozenset()
