import pytest

from app.config.immediate_prices import DEFAULT_IMMEDIATE_PRICES, duration_from_text, parse_prices

DEFAULT = {10: 3000, 20: 5000, 40: 10000, 60: 15000}


def test_default_prices_are_the_four_durations_agreed_with_the_client() -> None:
    prices = parse_prices(DEFAULT_IMMEDIATE_PRICES)
    assert prices == DEFAULT
    assert list(prices) == [10, 20, 40, 60]


def test_order_is_kept_and_spaces_are_tolerated() -> None:
    prices = parse_prices(" 40 : 10000 , 10:3000 ")
    assert prices == {40: 10000, 10: 3000}
    assert list(prices) == [40, 10]


@pytest.mark.parametrize(
    "raw",
    ["", "10", "10:", ":3000", "10:abc", "dez:3000", "10:3000,10:4000", "0:3000", "10:0", "10:30.00", "10:3000;20:5000", "10:3000,", "300:3000"],
)
def test_anything_malformed_gives_no_prices_so_immediate_care_stays_closed(raw: str) -> None:
    assert parse_prices(raw) == {}


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("20 minutos", 20),
        ("60", 60),
        ("quero 40 minutos", 40),
        ("10 minutos", 10),
        ("30 minutos", None),
        ("120 minutos", None),
        ("uma hora", None),
        ("", None),
        (None, None),
    ],
)
def test_duration_comes_from_the_chosen_option(content: str | None, expected: int | None) -> None:
    assert duration_from_text(content, DEFAULT) == expected
