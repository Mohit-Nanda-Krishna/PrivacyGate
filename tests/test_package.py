"""The installed src-layout package and its planned module boundaries import."""

from importlib import import_module

import pytest


@pytest.mark.parametrize("module", [
    "privacygate",
    "privacygate.models",
    "privacygate.pipeline",
    "privacygate.extraction",
    "privacygate.extraction.pdf",
    "privacygate.extraction.docx",
    "privacygate.extraction.pptx",
    "privacygate.extraction.ocr",
    "privacygate.detection",
    "privacygate.detection.presidio_detector",
    "privacygate.detection.regex_detector",
    "privacygate.detection.custom_recognizers",
    "privacygate.detection.merger",
    "privacygate.redaction",
    "privacygate.redaction.redactor",
    "privacygate.validation",
    "privacygate.validation.privacy_gate",
    "privacygate.risk",
    "privacygate.risk.classifier",
    "privacygate.audit",
    "privacygate.audit.report",
])
def test_package_imports(module):
    assert import_module(module).__name__ == module
