from privacygate.models import ContentBlock
from privacygate.validation.residual_checks import independent_residual_checks


def make_block(text: str) -> ContentBlock:
    return ContentBlock(
        block_id="test_block",
        text=text,
        page_number=1,
        paragraph_number=1,
    )


def test_ssn_shaped_value_is_classified_as_government_id():
    residuals = independent_residual_checks(
        [make_block("SSN: 123-45-6789")]
    )
    assert any(
        e.entity_type == "GOVERNMENT_ID"
        and e.detector == "gate:id_shape"
        for e in residuals
    )


def test_account_code_pattern_is_flagged_for_review():
    residuals = independent_residual_checks(
        [make_block("ACC-1234 RSK-5678 - vendor data High")]
    )
    assert any(
        e.entity_type == "GOVERNMENT_ID"
        and e.detector == "gate:id_shape"
        for e in residuals
    )


def test_redacted_ssn_placeholder_is_not_flagged_as_raw_id():
    residuals = independent_residual_checks(
        [make_block("SSN XX-XX-XXXX")]
    )
    assert not any(
        e.entity_type == "GOVERNMENT_ID"
        and e.detector == "gate:id_shape"
        for e in residuals
    )
