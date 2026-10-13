"""Gate accuracy: real OCR-damaged identifiers block, business records and places do not."""

import pytest

from privacygate.detection import detect_regex
from privacygate.models import ContentBlock, Document, PIIEntity
from privacygate.validation import validate_privacy
from privacygate.validation.residual_checks import independent_residual_checks


def _values(text, entity_type=None):
    return {text[e.start:e.end] for e in detect_regex(text) if entity_type in (None, e.entity_type)}


def _checks(text):
    block = ContentBlock("b", text)
    return {(e.detector, text[e.start:e.end]) for e in independent_residual_checks([block])}


# --- real residuals must be caught -----------------------------------------------

@pytest.mark.parametrize("text,value", [
    ("Reviewer note SSN 90.42.7781 recorded", "90.42.7781"),
    ("ssn: 123 45 6789", "123 45 6789"),
    ("Social Security Number 078.05.1120", "078.05.1120"),
])
def test_ocr_damaged_ssn_next_to_label(text, value):
    assert value in _values(text, "GOVERNMENT_ID")


def test_damaged_number_without_ssn_label_is_not_an_ssn():
    assert not _values("Section 90.42.7781 of the manual", "GOVERNMENT_ID")


@pytest.mark.parametrize("text,value", [
    ("Chair rachterberg @cadencefg.cor today", "rachterberg @cadencefg.cor"),
    ("mail a.okafor@cadencefg.con now", "a.okafor@cadencefg.con"),
    ("tlindqvist@cadencefg.c", "tlindqvist@cadencefg.c"),
])
def test_ocr_split_org_emails(text, value):
    assert value in _values(text, "EMAIL_ADDRESS")


def test_gate_still_catches_split_email_and_damaged_ssn_left_in_text():
    doc = Document("d", "s.pdf", "pdf", blocks=[
        ContentBlock("b1", "Chair rachterberg @cadencefg.cor today"),
        ContentBlock("b2", "Reviewer note SSN 90.42.7781 recorded"),
    ])
    result = validate_privacy(doc)
    assert result.status == "BLOCKED"
    assert len(result.residual_entities) >= 2


# --- false residuals must not block ---------------------------------------------

@pytest.mark.parametrize("text", [
    "ACC-2026-018 RSK-4488 residual access accepted",
    "ACC-2025-029 RSK-4433 legacy platform",
    "ISS-2026-0112 owner, INC-2026-0417 closed, BRC-2026-011 open",
    "PBR-2026-008 referred, EXC-2025-118 extended, CHL-2026-031 upheld",
])
def test_business_record_references_are_not_personal_ids(text):
    assert not [d for d, _ in _checks(text) if d == "gate:id_shape"]


def test_real_personnel_and_account_ids_still_flagged():
    found = _checks("Owner EMP-38104, account ACC-123456, vendor MER-IN-4471")
    assert {("gate:id_shape", "EMP-38104"), ("gate:id_shape", "ACC-123456"),
            ("gate:id_shape", "MER-IN-4471")} <= found


@pytest.mark.parametrize("text", [
    "System Administrator May 22. 2024 10:15 AM",
    "Auditor May 21, 2024 02-18 PM",
    "logged 2024 06 11 09 15",
    "2026-06-11700;44:512 file.export",  # ISO "T" read as 7
    "2626-06-11719:02:902 issue.create",  # ... and as 1, with a damaged year
])
def test_timestamps_are_not_digit_runs(text):
    assert not [d for d, _ in _checks(text) if d == "gate:digit_run"]


def test_log_noise_next_to_at_sign_is_not_an_email():
    assert not [d for d, _ in _checks("2026-06-11 08:18:022 @uTN.failure user") if d == "gate:email_shape"]


def test_email_shapes_with_digit_local_part_still_flagged_without_a_space():
    assert ("gate:email_shape", "4471@cadencefg.com") in _checks("ref 4471@cadencefg.com")
    assert ("gate:email_shape", "rachterberg @cadencefg.cor") in _checks("rachterberg @cadencefg.cor")


def test_phone_shaped_runs_still_flagged():
    assert ("gate:digit_run", "+1 (212) 555 0147") in _checks("call +1 (212) 555 0147 now")
    assert ("gate:digit_run", "2024 555 0199") in _checks("line 2024 555 0199 ext")


def test_place_names_found_only_by_ner_do_not_block(monkeypatch):
    doc = Document("d", "s.pdf", "pdf", blocks=[ContentBlock("b1", "Head of Risk [PERSON_001] New York 24F")])
    place = PIIEntity("LOCATION", 32, 40, 0.85, "presidio:SpacyRecognizer", "b1")
    monkeypatch.setattr("privacygate.validation.privacy_gate.detect_pii", lambda d: [place])
    result = validate_privacy(doc, issued_tokens=frozenset({"[PERSON_001]"}))
    assert result.status == "APPROVED"


def test_street_addresses_still_block():
    doc = Document("d", "s.pdf", "pdf", blocks=[
        ContentBlock("b1", "Home: 12 Maple Court, Apt 3B, Springfield, IL 62704")])
    assert validate_privacy(doc).status == "BLOCKED"
