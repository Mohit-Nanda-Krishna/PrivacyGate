"""False-positive controls for PAN, PESEL, TIN and card numbers (synthetic values only)."""

import pytest

from privacygate.detection import detect_regex
from privacygate.detection.regex_detector import _card_issuer_ok, _luhn_checksum, _pesel_valid


def _found(text: str, entity_type: str) -> set[str]:
    return {text[e.start:e.end] for e in detect_regex(text) if e.entity_type == entity_type}


def _with_luhn_digit(prefix: str) -> str:
    """Append the Luhn check digit to a numeric prefix."""
    for digit in "0123456789":
        if _luhn_checksum(prefix + digit):
            return prefix + digit
    raise AssertionError("unreachable")


@pytest.mark.parametrize("text,value", [
    ("Vendor TIN: 12-3456789 on file", "12-3456789"),
    ("EIN 98-7654321", "98-7654321"),
    ("Taxpayer Identification Number 123456789.", "123456789"),
    ("tax id #45-6789012", "45-6789012"),
])
def test_tin_is_detected_only_with_a_label(text, value):
    assert value in _found(text, "GOVERNMENT_ID")


@pytest.mark.parametrize("text", ["Ref 12-3456789 approved", "Batch 98-7654321 closed", "Order 123456789"])
def test_unlabelled_tin_shapes_are_not_pii(text):
    assert not [e for e in detect_regex(text) if e.detector.startswith("regex:tin")]


def test_pesel_checksum_and_date():
    assert _pesel_valid("44051401359")  # published PESEL format example
    assert not _pesel_valid("44051401358")  # wrong check digit
    assert not _pesel_valid("44131401350")  # month 13 is not encodable


def test_unlabelled_pesel_needs_valid_checksum():
    assert "44051401359" in _found("Record 44051401359 archived", "GOVERNMENT_ID")
    assert not _found("Record 44051401358 archived", "GOVERNMENT_ID")
    assert not _found("Tracking 12345678901 shipped", "GOVERNMENT_ID") or _pesel_valid("12345678901")


def test_labelled_partially_masked_pesel_still_detected():
    assert "890412xxxxx" in _found("PESEL 890412xxxxx", "GOVERNMENT_ID")


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "378282246310005", "5555555555554444"])
def test_real_scheme_cards_are_detected(number):
    assert number in _found(f"Card {number} used", "CREDIT_CARD")


@pytest.mark.parametrize("prefix", ["123456789012345", "900000000000000", "1000000000000"])
def test_luhn_valid_numbers_without_an_issuer_prefix_are_not_cards(prefix):
    number = _with_luhn_digit(prefix)
    assert _luhn_checksum(number) and not _card_issuer_ok(number)
    assert not _found(f"Reference {number} logged", "CREDIT_CARD")


@pytest.mark.parametrize("value,expected", [("ABCPD1234E", True), ("ABCXD1234E", False), ("ABCPD12345", False)])
def test_pan_requires_holder_type_letter(value, expected):
    assert (value in _found(f"PAN {value}", "GOVERNMENT_ID")) is expected
