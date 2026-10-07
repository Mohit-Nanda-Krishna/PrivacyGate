"""Risk classification for detected PII entities based on sensitivity tiers."""

from __future__ import annotations

from typing import Sequence
from privacygate.models import PIIEntity, RiskLevel

# Explicit risk mappings per PRD Section 16
RISK_MAPPING: dict[str, RiskLevel] = {
    # CRITICAL: Government IDs, Bank Accounts, Payment Cards, Highly sensitive financial data
    "GOVERNMENT_ID": "CRITICAL",
    "US_SSN": "CRITICAL",
    "US_PASSPORT": "CRITICAL",
    "US_DRIVER_LICENSE": "CRITICAL",
    "MEDICAL_LICENSE": "CRITICAL",
    "CREDIT_CARD": "CRITICAL",
    "ACCOUNT_NUMBER": "CRITICAL",
    "IBAN_CODE": "CRITICAL",
    "CRYPTO_ADDRESS": "CRITICAL",

    # HIGH: Employee/Client/Customer identifiers, contact details, addresses
    "EMPLOYEE_ID": "HIGH",
    "CLIENT_ID": "HIGH",
    "CUSTOMER_ID": "HIGH",
    "CUSTOMER_REF": "HIGH",
    "PORTFOLIO_ID": "HIGH",
    "PROJECT_CODE": "HIGH",
    "EMAIL": "HIGH",
    "EMAIL_ADDRESS": "HIGH",
    "PHONE": "HIGH",
    "PHONE_NUMBER": "HIGH",
    "ADDRESS": "HIGH",

    # MEDIUM: Names, locations, dates, lower-risk contextual markers
    "PERSON": "MEDIUM",
    "LOCATION": "MEDIUM",
    "IP_ADDRESS": "MEDIUM",
    "DATE_TIME": "MEDIUM",
    "URL": "MEDIUM",
    "NRP": "MEDIUM",
}


def get_risk_level(entity_type: str) -> RiskLevel:
    """Determine the risk level for a given entity type, defaulting to MEDIUM."""
    return RISK_MAPPING.get(entity_type.upper(), "MEDIUM")


def classify_entity_risk(entity: PIIEntity) -> PIIEntity:
    """Assign or update risk_level on a PIIEntity."""
    entity.risk_level = get_risk_level(entity.entity_type)
    return entity


def classify_risks(entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """Assign risk levels to all entities in a collection."""
    classified: list[PIIEntity] = []
    for entity in entities:
        classify_entity_risk(entity)
        classified.append(entity)
    return classified


def summarize_risks(entities: Sequence[PIIEntity]) -> dict[RiskLevel, int]:
    """Aggregate entity counts by risk level."""
    summary: dict[RiskLevel, int] = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
    }
    for entity in entities:
        level = entity.risk_level or get_risk_level(entity.entity_type)
        summary[level] = summary.get(level, 0) + 1
    return summary
