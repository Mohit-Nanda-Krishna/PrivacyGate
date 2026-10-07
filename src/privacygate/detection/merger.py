"""Deterministic entity merging, deduplication, and overlap resolution."""

from __future__ import annotations

from typing import Sequence
from privacygate.models import PIIEntity

# Detector authority rank (higher is more authoritative)
DETECTOR_PRIORITY: dict[str, int] = {
    "custom_enterprise": 30,
    "regex": 20,
    "presidio": 10,
}

# Type specificity rank
TYPE_SPECIFICITY: dict[str, int] = {
    "EMPLOYEE_ID": 30,
    "CLIENT_ID": 30,
    "PORTFOLIO_ID": 30,
    "CUSTOMER_REF": 30,
    "CREDIT_CARD": 25,
    "GOVERNMENT_ID": 25,
    "ACCOUNT_NUMBER": 25,
    "EMAIL": 20,
    "PHONE": 20,
    "IP_ADDRESS": 20,
    "PERSON": 15,
    "LOCATION": 10,
    "DATE_TIME": 5,
    "URL": 5,
}


def _spans_overlap(e1: PIIEntity, e2: PIIEntity) -> bool:
    """Return True if two entities in the same block have overlapping spans."""
    return max(e1.start, e2.start) < min(e1.end, e2.end)


def _resolve_cluster(cluster: list[PIIEntity]) -> PIIEntity:
    """Deterministically resolve a cluster of overlapping entities into a single canonical PIIEntity."""
    if len(cluster) == 1:
        return cluster[0]

    # Combine all unique detectors
    all_detectors: list[str] = []
    for e in cluster:
        for d in e.detector.split(","):
            d_clean = d.strip()
            if d_clean and d_clean not in all_detectors:
                all_detectors.append(d_clean)
    combined_detector = ",".join(all_detectors)

    # Pick the winning entity based on:
    # 1. Detector priority
    # 2. Entity type specificity
    # 3. Confidence score
    # 4. Span coverage (longer span)
    def _rank_key(entity: PIIEntity) -> tuple[int, int, float, int]:
        det_rank = max(DETECTOR_PRIORITY.get(d.strip(), 0) for d in entity.detector.split(","))
        type_rank = TYPE_SPECIFICITY.get(entity.entity_type, 0)
        span_len = entity.end - entity.start
        return (det_rank, type_rank, entity.confidence, span_len)

    winner = max(cluster, key=_rank_key)
    max_confidence = max(e.confidence for e in cluster)

    # Use winning bounds and winning type, but combined detector and max confidence
    return PIIEntity(
        entity_type=winner.entity_type,
        start=winner.start,
        end=winner.end,
        confidence=round(max_confidence, 3),
        detector=combined_detector,
        block_id=winner.block_id,
        source_location=dict(winner.source_location),
        risk_level=winner.risk_level,
    )


def merge_entities(entities: Sequence[PIIEntity]) -> list[PIIEntity]:
    """Deduplicate and merge detected entities deterministically.

    Overlapping or identical spans within the same block are clustered and resolved
    by prioritizing enterprise recognizers, structured regexes, and highest confidence.
    """
    if not entities:
        return []

    # Group entities by block_id
    by_block: dict[str, list[PIIEntity]] = {}
    for entity in entities:
        by_block.setdefault(entity.block_id, []).append(entity)

    merged: list[PIIEntity] = []

    for _, block_entities in by_block.items():
        # Sort by start offset ascending, then by span length descending
        sorted_entities = sorted(
            block_entities,
            key=lambda e: (e.start, -(e.end - e.start)),
        )

        # Form overlap clusters
        clusters: list[list[PIIEntity]] = []
        for entity in sorted_entities:
            placed = False
            for cluster in clusters:
                # If overlaps with any entity in the cluster
                if any(_spans_overlap(entity, existing) for existing in cluster):
                    cluster.append(entity)
                    placed = True
                    break
            if not placed:
                clusters.append([entity])

        # Resolve each cluster
        for cluster in clusters:
            resolved = _resolve_cluster(cluster)
            merged.append(resolved)

    # Sort final entities by block_id, start offset, end offset
    return sorted(merged, key=lambda e: (e.block_id, e.start, e.end))
