"""Tests for Phase 2 hybrid PII detection (Regex, Custom, Presidio, Merger)."""

from __future__ import annotations

import re
import pytest

from privacygate.detection import (
    CustomRecognizer,
    EnterprisePattern,
    detect_custom,
    detect_pii,
    detect_pii_in_block,
    detect_presidio,
    detect_regex,
    merge_entities,
)
from privacygate.models import ContentBlock, Document, PIIEntity


# --- 1. Regex Detector Tests ---

def test_detect_regex_email() -> None:
    text = "Please reach out to support@example.com or user.name+tag@sub.domain.org."
    entities = detect_regex(text, block_id="b1")
    emails = [e for e in entities if e.entity_type == "EMAIL"]
    assert len(emails) == 2
    assert emails[0].start == text.index("support@example.com")
    assert emails[0].end == emails[0].start + len("support@example.com")
    assert emails[0].confidence == 1.0
    assert emails[0].detector == "regex"


def test_detect_regex_phone() -> None:
    text = "Call us at +1 (555) 234-5678 or 555-876-5432."
    entities = detect_regex(text, block_id="b2")
    phones = [e for e in entities if e.entity_type == "PHONE"]
    assert len(phones) >= 1
    for p in phones:
        assert p.confidence >= 0.90
        assert p.detector == "regex"


def test_detect_regex_ssn() -> None:
    text = "The applicant's SSN is 123-45-6789."
    entities = detect_regex(text, block_id="b3")
    ssns = [e for e in entities if e.entity_type == "GOVERNMENT_ID"]
    assert len(ssns) == 1
    assert text[ssns[0].start:ssns[0].end] == "123-45-6789"


def test_detect_regex_ssn_invalid_ignored() -> None:
    text = "Invalid SSNs: 000-12-3456 and 666-45-6789 should not match."
    entities = detect_regex(text, block_id="b3")
    ssns = [e for e in entities if e.entity_type == "GOVERNMENT_ID"]
    assert len(ssns) == 0


def test_detect_regex_ip_address() -> None:
    text = "Connecting from host 192.168.1.100 and external 10.0.0.1, ignore 999.999.999.999."
    entities = detect_regex(text, block_id="b4")
    ips = [e for e in entities if e.entity_type == "IP_ADDRESS"]
    assert len(ips) == 2
    assert text[ips[0].start:ips[0].end] == "192.168.1.100"
    assert text[ips[1].start:ips[1].end] == "10.0.0.1"


def test_detect_regex_credit_card_luhn() -> None:
    # Valid test card number (satisfies Luhn)
    # Invalid card number (fails Luhn)
    valid_card = "4532 0150 1234 5671"
    invalid_card = "4532 0150 1234 5672"
    text = f"Valid card: {valid_card}. Invalid card: {invalid_card}."
    entities = detect_regex(text, block_id="b5")
    cards = [e for e in entities if e.entity_type == "CREDIT_CARD"]
    assert len(cards) == 1
    assert text[cards[0].start:cards[0].end] == valid_card


def test_detect_regex_empty() -> None:
    assert detect_regex("", block_id="b0") == []


# --- 2. Custom Enterprise Recognizer Tests ---

def test_detect_custom_employee_id() -> None:
    text = "Employee John is EMP-94821 and Employee ID: 83921."
    entities = detect_custom(text, block_id="c1")
    emp_entities = [e for e in entities if e.entity_type == "EMPLOYEE_ID"]
    assert len(emp_entities) == 2
    assert text[emp_entities[0].start:emp_entities[0].end] == "EMP-94821"
    assert text[emp_entities[1].start:emp_entities[1].end] == "83921"


def test_detect_custom_client_and_portfolio_ids() -> None:
    text = "Client ID: C-839201 holds Portfolio ID: AX-9832."
    entities = detect_custom(text, block_id="c2")
    types = {e.entity_type for e in entities}
    assert "CLIENT_ID" in types
    assert "PORTFOLIO_ID" in types


def test_detect_custom_customer_ref_and_account() -> None:
    text = "Refer to Customer Ref: CR-19382 for Account Number: ACC-82910."
    entities = detect_custom(text, block_id="c3")
    types = {e.entity_type for e in entities}
    assert "CUSTOMER_REF" in types
    assert "ACCOUNT_NUMBER" in types


def test_custom_recognizer_dynamic_pattern() -> None:
    recognizer = CustomRecognizer()
    recognizer.add_pattern(
        EnterprisePattern(
            name="Project Secret Code",
            entity_type="PROJECT_CODE",
            pattern=re.compile(r"\bPROJ-[A-Z]{3}-\d{3}\b"),
            confidence=0.99,
        )
    )
    text = "Accessing confidential project PROJ-SEC-404."
    results = recognizer.detect(text, block_id="dyn1")
    assert len(results) == 1
    assert results[0].entity_type == "PROJECT_CODE"
    assert text[results[0].start:results[0].end] == "PROJ-SEC-404"


# --- 3. Presidio Detector Tests ---

def test_detect_presidio_names_and_locations() -> None:
    text = "Sarah Connor traveled to Boston for the conference."
    entities = detect_presidio(text, block_id="p1")
    types = {e.entity_type for e in entities}
    assert "PERSON" in types
    # Check that Sarah Connor or Sarah was identified as PERSON
    person = next(e for e in entities if e.entity_type == "PERSON")
    assert person.detector == "presidio"
    assert person.confidence > 0.5


def test_detect_presidio_empty() -> None:
    assert detect_presidio("", block_id="p0") == []
    assert detect_presidio("   ", block_id="p0") == []


# --- 4. Merger Tests ---

def test_merge_exact_duplicates() -> None:
    e1 = PIIEntity(
        entity_type="EMAIL",
        start=10,
        end=25,
        confidence=0.85,
        detector="presidio",
        block_id="b1",
    )
    e2 = PIIEntity(
        entity_type="EMAIL",
        start=10,
        end=25,
        confidence=1.0,
        detector="regex",
        block_id="b1",
    )
    merged = merge_entities([e1, e2])
    assert len(merged) == 1
    assert merged[0].entity_type == "EMAIL"
    assert merged[0].confidence == 1.0
    assert "regex" in merged[0].detector
    assert "presidio" in merged[0].detector


def test_merge_overlapping_spans_prefers_enterprise() -> None:
    # E.g. Presidio detects "EMP-12345" as generic, but custom recognizes it as EMPLOYEE_ID
    e_nlp = PIIEntity(
        entity_type="GENERIC",
        start=0,
        end=9,
        confidence=0.70,
        detector="presidio",
        block_id="b1",
    )
    e_custom = PIIEntity(
        entity_type="EMPLOYEE_ID",
        start=0,
        end=9,
        confidence=0.98,
        detector="custom_enterprise",
        block_id="b1",
    )
    merged = merge_entities([e_nlp, e_custom])
    assert len(merged) == 1
    assert merged[0].entity_type == "EMPLOYEE_ID"
    assert merged[0].confidence == 0.98
    assert "custom_enterprise" in merged[0].detector


def test_merge_non_overlapping_preserves_both() -> None:
    e1 = PIIEntity(entity_type="PERSON", start=0, end=5, confidence=0.9, detector="presidio", block_id="b1")
    e2 = PIIEntity(entity_type="EMAIL", start=10, end=20, confidence=1.0, detector="regex", block_id="b1")
    merged = merge_entities([e1, e2])
    assert len(merged) == 2
    assert merged[0].start == 0
    assert merged[1].start == 10


# --- 5. Document-Level Hybrid Detection Tests ---

def test_detect_pii_document_integration() -> None:
    block1 = ContentBlock(
        block_id="block_p1_1",
        text="Employee Jane Doe (EMP-88392) filed report.",
        page_number=1,
        paragraph_number=1,
        extraction_method="pdf_native",
    )
    block2 = ContentBlock(
        block_id="block_p1_2",
        text="Contact email: jane.doe@cadence.com from IP 192.168.1.50.",
        page_number=1,
        paragraph_number=2,
        extraction_method="pdf_native",
    )
    doc = Document(
        document_id="doc_test_101",
        filename="test_report.pdf",
        file_type="pdf",
        blocks=[block1, block2],
    )

    entities = detect_pii(doc)
    assert len(entities) >= 3

    # Check source location tracking
    for ent in entities:
        assert ent.block_id in ("block_p1_1", "block_p1_2")
        assert ent.source_location.get("page_number") == 1
        assert ent.source_location.get("extraction_method") == "pdf_native"

    types = {e.entity_type for e in entities}
    assert "EMPLOYEE_ID" in types
    assert "EMAIL" in types
    assert "IP_ADDRESS" in types


def test_detect_pii_empty_document() -> None:
    doc = Document(document_id="empty", filename="empty.pdf", file_type="pdf", blocks=[])
    assert detect_pii(doc) == []
