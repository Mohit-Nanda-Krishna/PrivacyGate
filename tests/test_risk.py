"""Tests for Phase 3 risk classification."""

from privacygate.models import PIIEntity
from privacygate.risk import classify_entity_risk, classify_risks, get_risk_level, summarize_risks


def test_get_risk_level() -> None:
    assert get_risk_level("GOVERNMENT_ID") == "CRITICAL"
    assert get_risk_level("CREDIT_CARD") == "CRITICAL"
    assert get_risk_level("ACCOUNT_NUMBER") == "CRITICAL"
    assert get_risk_level("EMPLOYEE_ID") == "HIGH"
    assert get_risk_level("EMAIL") == "HIGH"
    assert get_risk_level("PHONE") == "HIGH"
    assert get_risk_level("PERSON") == "MEDIUM"
    assert get_risk_level("LOCATION") == "MEDIUM"
    assert get_risk_level("UNKNOWN_TYPE") == "MEDIUM"


def test_classify_entity_risk() -> None:
    ent = PIIEntity(
        entity_type="CREDIT_CARD",
        start=0,
        end=16,
        confidence=1.0,
        detector="regex",
        block_id="b1",
    )
    assert ent.risk_level is None
    classify_entity_risk(ent)
    assert ent.risk_level == "CRITICAL"


def test_summarize_risks() -> None:
    entities = [
        PIIEntity(entity_type="GOVERNMENT_ID", start=0, end=11, confidence=1.0, detector="regex", block_id="b1"),
        PIIEntity(entity_type="EMAIL", start=12, end=25, confidence=1.0, detector="regex", block_id="b1"),
        PIIEntity(entity_type="PERSON", start=30, end=40, confidence=0.9, detector="presidio", block_id="b1"),
    ]
    classify_risks(entities)
    summary = summarize_risks(entities)
    assert summary["CRITICAL"] == 1
    assert summary["HIGH"] == 1
    assert summary["MEDIUM"] == 1
