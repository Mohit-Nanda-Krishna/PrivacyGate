"""Detection errors and normalization shared by the three local detectors."""

from math import isfinite

from privacygate.models import ContentBlock, PIIEntity


class DetectionError(Exception):
    """Detection could not complete; no partial successful result is returned."""


def validate_entity(entity: PIIEntity) -> None:
    if (not entity.block_id or not entity.entity_type or not entity.detector
            or type(entity.start) is not int or type(entity.end) is not int
            or not 0 <= entity.start < entity.end
            or type(entity.confidence) not in (int, float)
            or not isfinite(entity.confidence) or not 0 <= entity.confidence <= 1):
        raise DetectionError("Detector returned an invalid entity span or confidence.")


def make_entity(
    block: ContentBlock, entity_type: str, start: int, end: int,
    confidence: float, detector: str,
) -> PIIEntity:
    """Offsets are Python character indices [start, end) into block.text.

    Copy only structural positions, never arbitrary metadata or matched text.
    Bounding boxes remain available through the original block_id association.
    """
    location = {
        key: value for key in ("page_number", "slide_number", "paragraph_number")
        if (value := getattr(block, key)) is not None
    }
    for key in (
        "body_index", "table_number", "row_number", "column_number", "shape_id",
        "shape_index", "block_order", "source_block_number", "source_paragraph_number",
        "source_line_number",
    ):
        value = block.metadata.get(key)
        if type(value) is int:
            location[key] = value
    shape_path = block.metadata.get("shape_path")
    if isinstance(shape_path, list) and all(type(value) is int for value in shape_path):
        location["shape_path"] = ".".join(map(str, shape_path))
    entity = PIIEntity(entity_type, start, end, confidence, detector, block.block_id, location)
    validate_entity(entity)
    if end > len(block.text):
        raise DetectionError("Detector returned an offset outside its content block.")
    return entity
