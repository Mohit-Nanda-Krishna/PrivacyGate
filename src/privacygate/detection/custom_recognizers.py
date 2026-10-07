"""Centralized labelled enterprise rules; spans include only the identifier."""

import re

from privacygate.detection.common import make_entity
from privacygate.models import ContentBlock, PIIEntity

# Extend labels/prefixes here after reviewing supplied artifacts. A label plus
# colon, equals, or hash is required; unlabelled codes are deliberately ignored.
CUSTOM_RULES = (
    ("EMPLOYEE_ID", r"employee[ \t]+(?:id|no\.?|number)", r"(?:EMP-\d{4,10}|\d{5,10})"),
    ("CLIENT_ID", r"client[ \t]+id", r"(?:(?:CLI|C)-\d{4,10}|\d{5,10})"),
    ("CUSTOMER_ID", r"customer[ \t]+id", r"(?:CUST-\d{4,10}|\d{5,10})"),
    ("PORTFOLIO_ID", r"portfolio[ \t]+id", r"(?:(?:PF|AX)-\d{4,10}|\d{5,10})"),
)
CUSTOM_PATTERNS = tuple(
    (entity_type, re.compile(
        rf"\b{label}[ \t]*(?::|=|#)[ \t]*(?P<value>{value})(?![\w-])", re.IGNORECASE,
    )) for entity_type, label, value in CUSTOM_RULES
)


def detect_custom(block: ContentBlock) -> list[PIIEntity]:
    return [make_entity(
        block, entity_type, *match.span("value"), 0.95, "custom:" + entity_type.lower(),
    ) for entity_type, pattern in CUSTOM_PATTERNS for match in pattern.finditer(block.text)]
