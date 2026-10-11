import json

from privacygate.audit.residual_diagnostics import build_residual_diagnostics
from privacygate.models import PIIEntity


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

