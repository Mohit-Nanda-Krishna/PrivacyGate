"""Explicit local Presidio baseline with spaCy PERSON/LOCATION recognition."""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import Sequence

import spacy
from presidio_analyzer import AnalyzerEngine, Pattern, RecognizerRegistry
from presidio_analyzer.nlp_engine import NerModelConfiguration, SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IbanRecognizer,
    IpRecognizer,
    PhoneRecognizer,
    SpacyRecognizer,
    UsSsnRecognizer,
)
from tldextract import TLDExtract

from privacygate.detection.common import DetectionError, make_entity
from privacygate.models import ContentBlock, PIIEntity

SPACY_MODEL = "en_core_web_sm"
SUPPORTED_ENTITIES = (
    "PERSON",
    "LOCATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "US_SSN",
    "IBAN_CODE",
)
SCORE_THRESHOLD = 0.4
_LOCAL_SUFFIXES = TLDExtract(suffix_list_urls=(), cache_dir=None)


class _OfflineEmailRecognizer(EmailRecognizer):
    """Use the bundled public-suffix snapshot without network or disk caches."""

    def validate_result(self, pattern_text: str) -> bool:
        return _LOCAL_SUFFIXES(pattern_text).fqdn != ""


@lru_cache(maxsize=1)
def get_analyzer() -> AnalyzerEngine:
    """Cache only the engine, never documents/results. Never download at runtime."""
    try:
        # Presidio debug context messages can contain words from the input.
        logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)
        model = spacy.load(SPACY_MODEL)
        if "ner" not in model.pipe_names:
            raise ValueError("NER component is required")
        mapping = {"PERSON": "PERSON", "GPE": "LOCATION", "LOC": "LOCATION"}
        nlp_engine = SpacyNlpEngine(
            models=[{"lang_code": "en", "model_name": SPACY_MODEL}],
            ner_model_configuration=NerModelConfiguration(
                model_to_presidio_entity_mapping=mapping,
                labels_to_ignore=sorted(set(model.get_pipe("ner").labels) - mapping.keys()),
            ),
        )
        # Inject the already-loaded local pipeline to prevent runtime downloads.
        nlp_engine.nlp = {"en": model}
        registry = RecognizerRegistry(
            supported_languages=["en"],
            recognizers=[
                SpacyRecognizer(supported_entities=["PERSON", "LOCATION"]),
                _OfflineEmailRecognizer(name="EmailRecognizer"),
                PhoneRecognizer(supported_regions=["US", "GB", "IN"], leniency=2),
                IpRecognizer(),
                CreditCardRecognizer(),
                IbanRecognizer(),
                UsSsnRecognizer(
                    patterns=[
                        Pattern("Formatted SSN", r"(?<!\w)\d{3}-\d{2}-\d{4}(?!\w)", 0.5),
                    ]
                ),
            ],
        )
        return AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["en"],
            default_score_threshold=SCORE_THRESHOLD,
            log_decision_process=False,
        )
    except Exception:
        raise DetectionError(
            "Local Presidio/spaCy initialization failed. Run uv sync --locked to install "
            "the pinned en_core_web_sm model. Detection did not complete."
        ) from None


class PresidioDetector:
    """Presidio analyzer wrapper providing access to AnalyzerEngine."""

    def __init__(self, score_threshold: float = SCORE_THRESHOLD) -> None:
        self.score_threshold = score_threshold

    @property
    def engine(self) -> AnalyzerEngine:
        return get_analyzer()

    def detect(self, block: ContentBlock | str, block_id: str = "") -> list[PIIEntity]:
        return detect_presidio(block, block_id=block_id)


_DEFAULT_PRESIDIO = PresidioDetector()


def detect_presidio(block: ContentBlock | str, block_id: str = "") -> list[PIIEntity]:
    """Analyze one block; expose recognizer names but no explanation/raw values."""
    if isinstance(block, str):
        content_block = ContentBlock(block_id=block_id or "block", text=block)
    else:
        content_block = block

    if not content_block.text or not content_block.text.strip():
        return []

    analyzer = get_analyzer()
    try:
        logging.getLogger("presidio-analyzer").setLevel(logging.WARNING)
        results = analyzer.analyze(
            text=content_block.text,
            language="en",
            entities=list(SUPPORTED_ENTITIES),
            return_decision_process=False,
        )
        return [
            make_entity(
                content_block,
                result.entity_type,
                result.start,
                result.end,
                result.score,
                "presidio:" + result.recognition_metadata.get("recognizer_name", "presidio"),
            )
            for result in results
        ]
    except Exception:
        raise DetectionError(
            "Presidio could not analyze a content block. Detection did not complete."
        ) from None
