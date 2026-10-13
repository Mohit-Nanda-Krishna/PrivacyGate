"""What a downstream AI model would receive, and a local mock of that call.

There is no network access and no API key: mock_llm_call() only demonstrates
the contract that sanitized text leaves PrivacyGate solely for APPROVED
documents. It refuses everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from privacygate.models import Document, ValidationResult

TOKEN_PATTERN = re.compile(r"\[[A-Z][A-Z_]*(?:_\d+)?\]")


class GateRefusedError(Exception):
    """The privacy gate did not approve the document, so nothing may be sent."""


@dataclass(frozen=True)
class MockLLMResponse:
    text: str
    characters_sent: int
    tokens_seen: int


def build_llm_payload(sanitized: Document) -> str:
    """The exact text a model would receive: sanitized blocks in document order."""
    return "\n".join(block.text for block in sanitized.blocks if block.text.strip())


def mock_llm_call(sanitized: Document, validation: ValidationResult, instruction: str) -> MockLLMResponse:
    """Pretend to send the sanitized payload to a model; refuse unless APPROVED.

    The reply is deterministic and built only from the sanitized payload.
    """
    if validation.status != "APPROVED":
        raise GateRefusedError(
            "Refused: the privacy gate has not approved this document, so no text is sent to the model."
        )
    payload = build_llm_payload(sanitized)
    tokens = TOKEN_PATTERN.findall(payload)
    distinct = list(dict.fromkeys(tokens))
    preview = ", ".join(distinct[:8]) + (" ..." if len(distinct) > 8 else "")
    reply = (
        f"[mock model] Instruction received: {instruction.strip()[:200] or '(none)'}\n"
        f"Received {len(payload):,} characters in {payload.count(chr(10)) + 1 if payload else 0} lines. "
        f"The text contains {len(tokens)} pseudonym tokens ({len(distinct)} distinct)"
        + (f": {preview}." if distinct else ".")
        + " No original personal data was included in this request."
    )
    return MockLLMResponse(text=reply, characters_sent=len(payload), tokens_seen=len(tokens))
