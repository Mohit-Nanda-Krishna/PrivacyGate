"""Targeted regex support: internal-domain emails and explicitly labelled phones."""

import re

from privacygate.detection.common import make_entity
from privacygate.models import ContentBlock, PIIEntity

# Unlike public-suffix validation, this also covers business addresses such as
# user@example.internal. No quoted local parts, IDN, or obfuscated emails yet.
EMAIL_PATTERN = re.compile(
    r"(?<![\w.@%+-])[A-Z0-9_%+-]+(?:\.[A-Z0-9_%+-]+)*@"
    r"[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)*\.[A-Z]{2,63}(?![\w@-])",
    re.IGNORECASE,
)
# Label + structured separators/E.164; never match arbitrary bare digit strings.
PHONE_PATTERN = re.compile(
    r"\b(?:phone|telephone|mobile|tel)[ \t]*:[ \t]*"
    r"(?P<value>(?:\+[1-9]\d{0,2}[ -])?(?:\(\d{2,4}\)|\d{2,4})"
    r"(?:[ -]\d{2,4}){2,3}|\+[1-9]\d{9,14})(?![\w-])",
    re.IGNORECASE,
)


def detect_regex(block: ContentBlock) -> list[PIIEntity]:
    entities = [make_entity(block, "EMAIL_ADDRESS", match.start(), match.end(), 0.95, "regex:email")
                for match in EMAIL_PATTERN.finditer(block.text)]
    for match in PHONE_PATTERN.finditer(block.text):
        if 10 <= sum(character.isdigit() for character in match["value"]) <= 15:
            entities.append(make_entity(
                block, "PHONE_NUMBER", *match.span("value"), 0.85, "regex:labelled_phone",
            ))
    return entities
