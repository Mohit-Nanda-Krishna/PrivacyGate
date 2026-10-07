"""Deterministic conservative union of overlapping spans within each block.

Exact duplicates use maximum confidence and sorted, unique detector provenance.
Overlapping components use the most specific type, then highest confidence,
longest span, earliest start, and lexical type/detector as tie breakers. The
winning type/confidence is applied to the UNION so partial-overlap tails are
not silently lost. Touching spans and different blocks are never combined.
Provenance lists all contributing sources, not agreement on the winning type.
"""

from dataclasses import replace
from itertools import groupby

from privacygate.detection.common import DetectionError, validate_entity
from privacygate.models import PIIEntity

SPECIFICITY = {
    "EMPLOYEE_ID": 3, "CLIENT_ID": 3, "CUSTOMER_ID": 3, "PORTFOLIO_ID": 3,
    "EMAIL_ADDRESS": 2, "PHONE_NUMBER": 2, "IP_ADDRESS": 2,
    "CREDIT_CARD": 2, "US_SSN": 2, "IBAN_CODE": 2,
    "PERSON": 1, "LOCATION": 1,
}


def _merge_component(entities: list[PIIEntity]) -> PIIEntity:
    winner = min(entities, key=lambda entity: (
        -SPECIFICITY.get(entity.entity_type, 0), -entity.confidence,
        -(entity.end - entity.start), entity.start, entity.entity_type, entity.detector,
    ))
    return replace(
        winner, start=min(entity.start for entity in entities),
        end=max(entity.end for entity in entities),
        detector="|".join(sorted({
            source for entity in entities for source in entity.detector.split("|")
        })), source_location=dict(winner.source_location),
    )


def merge_entities(entities: list[PIIEntity]) -> list[PIIEntity]:
    """Return new entities sorted by block_id/start; never mutate inputs."""
    for entity in entities:
        validate_entity(entity)
    merged = []
    ordered = sorted(entities, key=lambda entity: (entity.block_id, entity.start, entity.end))
    for _, block_entities in groupby(ordered, key=lambda entity: entity.block_id):
        block_entities = list(block_entities)
        if any(entity.source_location != block_entities[0].source_location for entity in block_entities):
            raise DetectionError("Detections in one block have conflicting source locations.")
        component = []
        end = -1
        for entity in block_entities:
            if component and entity.start >= end:
                merged.append(_merge_component(component))
                component = []
            component.append(entity)
            end = max(end, entity.end)
        if component:
            merged.append(_merge_component(component))
    return merged
