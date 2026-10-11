import json
from pathlib import Path
import re

from privacygate.audit import residual_diagnostics
from privacygate.audit.residual_diagnostics import build_residual_diagnostics
from privacygate.models import PIIEntity

SRC = Path(__file__).resolve().parents[1] / "src" / "privacygate"


def test_real_pipeline_values_are_kept():
    residuals = [
        PIIEntity("US_SSN", 0, 11, 1.0, "presidio:UsSsnRecognizer|regex:ssn", "b1",
                  {"page_number": 3, "extraction_method": "pdf_native"}),
        PIIEntity("PERSON", 0, 5, 0.85, "gate:name_registry|name_sweep", "b2",
                  {"slide_number": 2, "extraction_method": "pptx_native"}),
        PIIEntity("PERSON", 0, 5, 0.8, "context:role_name", "b3",
                  {"extraction_method": "embedded_image_ocr"}),
    ]
    assert build_residual_diagnostics(residuals) == [
        {"entity_type": "US_SSN", "detectors": ["presidio:UsSsnRecognizer", "regex:ssn"], "page": 3,
         "extraction_method": "pdf_native"},
        {"entity_type": "PERSON", "detectors": ["gate:name_registry", "name_sweep"], "page": None,
         "extraction_method": "pptx_native"},
        {"entity_type": "PERSON", "detectors": ["context:role_name"], "page": None,
         "extraction_method": "embedded_image_ocr"},
    ]


def test_every_detector_name_in_the_source_is_allowlisted():
    source = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py"))
    literal = set(re.findall(r'"((?:regex|custom|gate|context|pattern):[A-Za-z0-9_]+|name_sweep)"', source))
    gate_checks = {f"gate:{name}" for name in re.findall(r'"([a-z_]+)"\)', source)
                   if f'"{name}")' in source and name in {"name_registry", "digit_run", "email_shape",
                                                         "id_shape", "unissued_placeholder"}}
    custom_rules = {f"custom:{name.lower()}" for name in re.findall(r'\("([A-Z_]+)", r"[a-z]', source)}
    extraction = set(re.findall(r'extraction_method="([a-z_]+)"', source))
    allowed = residual_diagnostics._ALLOWED_DETECTORS
    assert literal | gate_checks | custom_rules <= allowed, sorted((literal | gate_checks | custom_rules) - allowed)
    assert extraction <= residual_diagnostics._ALLOWED_EXTRACTION_METHODS


def test_residual_diagnostics_allowlists_metadata_and_hides_private_values():
    secret = "SECRET_PERSON_VALUE_92731"
    private_block_id = "C:/private/employee-secret-document.pdf"
    filename = "employee-secret-document.pdf"

    residuals = [
        PIIEntity(
            entity_type="GOVERNMENT_ID",
            start=0,
            end=len(secret),
            confidence=0.99,
            detector="gate:id_shape",
            block_id=private_block_id,
            source_location={
                "page_number": 17,
                "extraction_method": "ocr",
                "shape_id": filename,
                "private_value": secret,
            },
        )
    ]

    exported = json.dumps(build_residual_diagnostics(residuals))

    assert json.loads(exported) == [{
        "entity_type": "GOVERNMENT_ID",
        "detectors": ["gate:id_shape"],
        "page": 17,
        "extraction_method": "ocr",
    }]

    for value in (secret, private_block_id, filename):
        assert value not in exported


def test_residual_diagnostics_sanitizes_unknown_metadata():
    secret_type = "SECRET_PERSON_VALUE_92731"
    secret_detector = "SECRET_DETECTOR_VALUE"
    secret_block_id = "private-block-identifier"

    residuals = [
        PIIEntity(
            entity_type=secret_type,
            start=0,
            end=6,
            confidence=0.9,
            detector=secret_detector,
            block_id=secret_block_id,
            source_location={
                "page_number": -1,
                "extraction_method": "private-method",
                "shape_id": secret_block_id,
            },
        )
    ]

    exported = json.dumps(build_residual_diagnostics(residuals))

    assert json.loads(exported) == [{
        "entity_type": "OTHER",
        "detectors": [],
        "page": None,
        "extraction_method": "unknown",
    }]

    for value in (secret_type, secret_detector, secret_block_id):
        assert value not in exported

