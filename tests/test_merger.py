from dataclasses import replace
from itertools import permutations

import pytest

from privacygate.detection import DetectionError
from privacygate.detection.merger import merge_entities
from privacygate.models import PIIEntity


def entity(kind="EMAIL_ADDRESS", start=0, end=10, confidence=0.8, detector="regex:email", block_id="b"):
    return PIIEntity(kind, start, end, confidence, detector, block_id)


def test_exact_duplicates_merge_max_confidence_and_sorted_provenance_without_mutation():
    first = entity(confidence=0.7)
    second = entity(confidence=0.95, detector="presidio:EmailRecognizer")
    result, = merge_entities([first, second, first])
    assert result.confidence == 0.95
    assert result.detector == "presidio:EmailRecognizer|regex:email"
    assert first.confidence == 0.7
    assert result is not second
    assert merge_entities([result, first]) == [result]


@pytest.mark.parametrize("items,kind,start,end,confidence", [
    ([entity("PERSON", 0, 15, 0.99, "presidio:SpacyRecognizer"), entity()], "EMAIL_ADDRESS", 0, 15, 0.8),
    ([entity("PHONE_NUMBER", 0, 10, 0.99), entity("EMPLOYEE_ID", 2, 8, 0.95, "custom:employee_id")],
     "EMPLOYEE_ID", 0, 10, 0.95),
    ([entity("PERSON", 0, 10, 0.8), entity("LOCATION", 5, 15, 0.9)], "LOCATION", 0, 15, 0.9),
    ([entity(start=0, end=10), entity(start=8, end=20), entity(start=19, end=30)], "EMAIL_ADDRESS", 0, 30, 0.8),
    ([entity("PERSON"), entity("LOCATION")], "LOCATION", 0, 10, 0.8),
])
def test_overlap_policy_is_deterministic_for_all_input_permutations(items, kind, start, end, confidence):
    expected = None
    for order in permutations(items):
        result = merge_entities(list(order))
        assert len(result) == 1
        assert (result[0].entity_type, result[0].start, result[0].end, result[0].confidence) == (kind, start, end, confidence)
        if expected is not None:
            assert result == expected
        expected = result


def test_touching_spans_and_different_blocks_never_merge():
    items = [entity(start=0, end=5), entity(start=5, end=10), entity(block_id="other")]
    assert len(merge_entities(items)) == 3


@pytest.mark.parametrize("changes", [
    {"start": -1}, {"end": 0}, {"end": 0.5}, {"confidence": -0.1},
    {"confidence": 1.1}, {"confidence": float("nan")}, {"confidence": "high"}, {"block_id": ""},
])
def test_invalid_spans_and_confidences_fail(changes):
    with pytest.raises(DetectionError):
        merge_entities([replace(entity(), **changes)])


def test_conflicting_source_locations_fail_instead_of_picking_arbitrarily():
    first = entity()
    second = replace(first, source_location={"page_number": 2})
    with pytest.raises(DetectionError, match="conflicting source locations"):
        merge_entities([first, second])
