"""Tests for the document-level ground truth benchmark (synthetic data only)."""

import csv
from pathlib import Path

import pytest

from privacygate.evaluation import (
    GroundTruthRow,
    build_page_texts,
    evaluate_document,
    find_value,
    load_ground_truth,
    locate_ground_truth,
)
from privacygate.models import ContentBlock, Document, PIIEntity


def _row(value, entity_type="PERSON", page="1", location_type="table", uncertain=False):
    return GroundTruthRow("sample.pdf", page, location_type, entity_type, value, uncertain)


def _doc(*blocks):
    return Document("doc-1", "sample.pdf", "pdf", blocks=list(blocks))


def _block(block_id, text, page=1, method="ocr", **metadata):
    return ContentBlock(block_id, text, page_number=page, extraction_method=method, metadata=metadata)


def _entity(block_id, text, value, entity_type="PERSON"):
    start = text.index(value)
    return PIIEntity(entity_type, start, start + len(value), 0.9, "test", block_id)


def test_find_value_ignores_spacing_and_punctuation():
    text = "Call +1 (555)\n010-2030 or +1 555 010 2030."
    assert len(find_value(text, "+1 (555) 010-2030")) == 2


def test_find_value_requires_word_boundaries():
    assert find_value("Jo Parkerson met Jo Park.", "Jo Park") == [(17, 24, False)]


def test_find_value_fuzzy_matches_ocr_damaged_names_only():
    hits = find_value("Owner: Quentin Abernathe", "Quentin Abernathy")
    assert len(hits) == 1 and hits[0][2] is True
    # Digit-heavy values must never match a different number fuzzily.
    assert find_value("+1 (555) 010-2031", "+1 (555) 010-2030") == []


def test_find_value_finds_ocr_variant_next_to_exact_match():
    text = "Quentin Abernathy signed; later Quentin Abernathe (OCR) signed again."
    hits = find_value(text, "Quentin Abernathy")
    assert [(text[s:e], is_fuzzy) for s, e, is_fuzzy in hits] == [
        ("Quentin Abernathy", False), ("Quentin Abernathe", True),
    ]


def test_longer_rows_claim_text_before_surname_rows():
    page = build_page_texts(_doc(_block("b1", "Quentin R. Abernathy and later Abernathy alone")))
    occurrences = locate_ground_truth([_row("Abernathy"), _row("Quentin R. Abernathy")], page)
    by_value = {}
    for occurrence in occurrences:
        by_value.setdefault(occurrence.row.value, []).append(occurrence)
    assert len(by_value["Quentin R. Abernathy"]) == 1
    assert len(by_value["Abernathy"]) == 1


def test_unextracted_row_counts_as_one_missed_image_occurrence():
    document = _doc(_block("b1", "Nothing personal here"))
    result = evaluate_document(document, [], [_row("Zelda Quark", location_type="image")])
    assert result.overall.occurrences == 1
    assert result.overall.recall == 0.0
    assert result.not_extracted == 1
    assert result.by_channel["image"].occurrences == 1


def test_recall_precision_residual_and_partial_redaction():
    text = "Contact Zelda Quark at TK1234567 or Fred."
    document = _doc(_block("b1", text))
    rows = [_row("Zelda Quark"), _row("TK1234567", "GOVERNMENT_ID")]
    entities = [
        _entity("b1", text, "Zelda Quark"),
        _entity("b1", text, "1234567", "PHONE_NUMBER"),  # partial: "TK" stays visible
        _entity("b1", text, "Fred"),  # not in ground truth -> false positive
    ]
    result = evaluate_document(document, entities, rows)
    assert result.overall.occurrences == 2
    assert result.overall.detected == 2
    assert result.overall.residual == 1  # TK1234567 only partially redacted
    assert result.overall.true_positives == 2
    assert result.overall.false_positives == 1
    assert result.overall.precision == pytest.approx(2 / 3)
    assert result.false_positive_types == {"PERSON": 1}


def test_uncertain_rows_are_neutral():
    text = "Mailbox team@example.test"
    document = _doc(_block("b1", text))
    rows = [_row("team@example.test", "EMAIL", uncertain=True)]
    result = evaluate_document(document, [_entity("b1", text, "team@example.test", "EMAIL_ADDRESS")], rows)
    assert result.overall.occurrences == 0
    assert result.overall.true_positives == 0
    assert result.overall.false_positives == 0
    assert result.uncertain_rows == 1


def test_channel_split_uses_extraction_method_and_image_pages():
    native = ContentBlock("p1", "Zelda Quark", paragraph_number=1, extraction_method="docx_native")
    image = ContentBlock("i1", "Zelda Quark", extraction_method="embedded_image_ocr",
                         metadata={"image_name": "image7.png"})
    document = Document("d", "sample.docx", "docx", blocks=[native, image])
    rows = [_row("Zelda Quark", page=""), _row("Zelda Quark", page="image7.png", location_type="image")]
    result = evaluate_document(document, [PIIEntity("PERSON", 0, 11, 0.9, "t", "p1")], rows)
    assert result.by_channel["native"].recall == 1.0
    assert result.by_channel["image"].recall == 0.0


def test_load_ground_truth_reads_and_validates_columns(tmp_path: Path):
    path = tmp_path / "gt.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "page", "location_type", "entity_type", "value", "uncertain", "note"])
        writer.writerow(["a.pdf", "2", "prose", "PERSON", "Zelda Quark", "yes", "check"])
        writer.writerow(["a.pdf", "2", "prose", "PERSON", "", "", "blank rows are skipped"])
    rows = load_ground_truth(path)
    assert rows == [GroundTruthRow("a.pdf", "2", "prose", "PERSON", "Zelda Quark", True, "check")]

    bad = tmp_path / "bad.csv"
    bad.write_text("file,value\na.pdf,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_ground_truth(bad)


def test_report_contains_counts_only():
    text = "Zelda Quark"
    result = evaluate_document(_doc(_block("b1", text)), [_entity("b1", text, text)], [_row(text)])
    assert "Zelda" not in str(result.to_dict())


def test_repository_ground_truth_files_are_well_formed():
    root = Path(__file__).resolve().parent.parent / "eval" / "ground_truth"
    files = sorted(root.glob("*.csv"))
    assert files, "ground truth CSVs are missing"
    allowed = {"body", "table", "prose", "image"}
    for path in files:
        rows = load_ground_truth(path)
        assert rows
        assert len({row.file for row in rows}) == 1
        assert {row.location_type for row in rows} <= allowed
