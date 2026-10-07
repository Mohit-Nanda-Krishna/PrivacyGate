"""Microsoft Presidio NLP-based entity detection wrapper."""

from __future__ import annotations

from typing import Any
from privacygate.models import PIIEntity

# Entity normalization mapping from Presidio types to PrivacyGate canonical types
PRESIDIO_TYPE_MAP: dict[str, str] = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "IP_ADDRESS": "IP_ADDRESS",
    "CREDIT_CARD": "CREDIT_CARD",
    "CRYPTO": "CRYPTO_ADDRESS",
    "IBAN_CODE": "ACCOUNT_NUMBER",
    "US_BANK_NUMBER": "ACCOUNT_NUMBER",
    "US_SSN": "GOVERNMENT_ID",
    "US_PASSPORT": "GOVERNMENT_ID",
    "US_DRIVER_LICENSE": "GOVERNMENT_ID",
    "MEDICAL_LICENSE": "GOVERNMENT_ID",
    "LOCATION": "LOCATION",
    "DATE_TIME": "DATE_TIME",
    "NRP": "NRP",
    "URL": "URL",
}


class PresidioDetector:
    """Lazy-loaded Presidio analyzer wrapper."""

    def __init__(self, score_threshold: float = 0.40) -> None:
        self.score_threshold = score_threshold
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        """Lazily load AnalyzerEngine to avoid import/initialization latency."""
        if self._engine is None:
            from presidio_analyzer import AnalyzerEngine
            self._engine = AnalyzerEngine()
        return self._engine

    def detect(self, text: str, block_id: str = "") -> list[PIIEntity]:
        """Scan text using Presidio Analyzer and return normalized PIIEntity objects."""
        if not text or not text.strip():
            return []

        try:
            results = self.engine.analyze(
                text=text,
                language="en",
                score_threshold=self.score_threshold,
            )
        except Exception:
            # Presidio failure must fail closed or propagate depending on pipeline requirements.
            # Here we propagate or re-raise if fatal, but return empty or raise.
            raise

        entities: list[PIIEntity] = []
        for res in results:
            canonical_type = PRESIDIO_TYPE_MAP.get(res.entity_type, res.entity_type)
            entities.append(
                PIIEntity(
                    entity_type=canonical_type,
                    start=res.start,
                    end=res.end,
                    confidence=round(float(res.score), 3),
                    detector="presidio",
                    block_id=block_id,
                )
            )
        return entities


_DEFAULT_PRESIDIO = PresidioDetector()


def detect_presidio(text: str, block_id: str = "", score_threshold: float = 0.40) -> list[PIIEntity]:
    """Scan text using default Presidio analyzer."""
    if score_threshold != _DEFAULT_PRESIDIO.score_threshold:
        return PresidioDetector(score_threshold=score_threshold).detect(text, block_id=block_id)
    return _DEFAULT_PRESIDIO.detect(text, block_id=block_id)
