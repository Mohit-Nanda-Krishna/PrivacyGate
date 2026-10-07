"""Batch-level pseudonym session and cross-file view (synthetic documents only)."""

from pathlib import Path

from docx import Document as DocxDocument
from streamlit.testing.v1 import AppTest

from privacygate.crossfile import describe_location
from privacygate.detection.names import NameRegistry, _Person, merge_registries
from privacygate.models import ContentBlock
from privacygate.pipeline import run_batch, run_pipeline

APP_PATH = Path(__file__).parents[1] / "app.py"


def _docx(path: Path, *paragraphs: str) -> Path:
    document = DocxDocument()
    for text in paragraphs:
        document.add_paragraph(text)
    document.save(path)
    return path


def _sanitized(result) -> str:
    return "\n".join(block.text for block in result.sanitized_document.blocks)


def _files(tmp_path: Path) -> list[Path]:
    first = _docx(
        tmp_path / "policy.docx",
        "Policy owner: Quentin R. Abernathy (q.abernathy@example.test).",
        "Escalations go to Q. Abernathy and to Ottoline V. Quarrington.",
    )
    second = _docx(
        tmp_path / "pack.docx",
        "Led by Quentin R. Abernathy, contact quentin.abernathy@example.org.",
        "Deputy: Hesper K. Vale.",
    )
    return [first, second]


def test_merge_registries_dedupes_people_and_keeps_distinct_middles():
    a = NameRegistry([_Person("Quentin", "Abernathy", ("R.",)), _Person(None, "Vale", (), "H")])
    b = NameRegistry([_Person("Quentin", "Abernathy", ()), _Person("Quentin", "Abernathy", ("S.",)),
                      _Person("Hesper", "Vale", ("K.",))])
    merged = merge_registries([a, b])
    names = sorted((p.first, p.last, p.middles) for p in merged.people)
    assert names == [("Hesper", "Vale", ("K.",)), ("Quentin", "Abernathy", ("R.",)),
                     ("Quentin", "Abernathy", ("S.",))]
    # Surname-only "Vale" is dropped because exactly one named Vale exists.
    assert merged.resolve_person("Hesper Vale") is not None


def test_same_person_gets_same_token_across_files(tmp_path):
    batch = run_batch(_files(tmp_path))
    policy, pack = (_sanitized(result) for result in batch.results)
    token = next(t for t in batch.cross_file if t.startswith("[PERSON_") and len(batch.cross_file[t].files) == 2)
    assert token in policy and token in pack
    assert "Abernathy" not in policy + pack
    summary = batch.cross_file[token]
    assert summary.files == ["policy.docx", "pack.docx"]
    assert summary.locations_text() == "policy.docx para 1, para 2; pack.docx para 1"


def test_email_keeps_own_token_and_links_to_person(tmp_path):
    batch = run_batch(_files(tmp_path))
    person = next(s for s in batch.cross_file.values() if s.entity_type == "PERSON" and len(s.files) == 2)
    assert len(person.linked_emails) == 2  # two different addresses, two EMAIL tokens
    for email_token in person.linked_emails:
        assert email_token.startswith("[EMAIL_")
        assert batch.cross_file[email_token].linked_person == person.token


def test_cross_file_index_holds_no_raw_values(tmp_path):
    batch = run_batch(_files(tmp_path))
    dump = repr(batch.cross_file) + "".join(s.locations_text() for s in batch.cross_file.values())
    for value in ("Abernathy", "Quarrington", "Vale", "example.test", "example.org"):
        assert value not in dump


def test_single_file_behaviour_is_unchanged(tmp_path):
    path = _files(tmp_path)[0]
    alone = run_pipeline(path)
    batched = run_batch([path])
    assert _sanitized(alone) == _sanitized(batched.results[0])
    assert alone.validation.status == batched.results[0].validation.status


def test_name_variants_share_one_token_in_a_single_file(tmp_path):
    # Regression: a surname-only registry entry ("Q. Abernathy") beside the full name made
    # resolve_person() ambiguous, so the variants got different tokens within one file.
    result = run_pipeline(_files(tmp_path)[0])
    text = _sanitized(result)
    assert text.count("[PERSON_001]") == 2  # "Quentin R. Abernathy" and "Q. Abernathy"
    assert "[PERSON_002]" in text  # Ottoline V. Quarrington


def test_tokens_restart_per_single_run(tmp_path):
    first, second = _files(tmp_path)
    assert "[PERSON_001]" in _sanitized(run_pipeline(first))
    assert "[PERSON_001]" in _sanitized(run_pipeline(second))  # independent session per run


def test_names_from_one_file_are_swept_in_another(tmp_path):
    first = _docx(tmp_path / "a.docx", "Owner Ottoline V. Quarrington signs off.")
    second = _docx(tmp_path / "b.docx", "Quarrington approved the change.")
    batch = run_batch([first, second])
    assert "Quarrington" not in _sanitized(batch.results[1])


def test_describe_location_labels():
    assert describe_location(ContentBlock("a", "x", page_number=3)) == "p.3"
    assert describe_location(ContentBlock("b", "x", slide_number=8)) == "slide 8"
    assert describe_location(ContentBlock("c", "x", paragraph_number=12)) == "para 12"
    assert describe_location(ContentBlock("d", "x", metadata={"kind": "table_cell", "table_number": 2})) == "table 2"
    assert describe_location(ContentBlock("e", "x", metadata={"image_name": "image7.png"})) == "image image7.png"
    assert describe_location(ContentBlock("f", "x", slide_number=2, metadata={"kind": "notes"})) == "slide 2 notes"
    assert describe_location(ContentBlock("g", "x", metadata={"kind": "header"})) == "header"


def test_app_renders_batch_overview_and_cross_file_tab(tmp_path):
    batch = run_batch(_files(tmp_path))
    app = AppTest.from_file(str(APP_PATH))
    app.session_state["batch_result"] = batch
    app.session_state["pipeline_result"] = batch.results[0]
    app.run(timeout=60)
    assert not app.exception
    assert any("Batch Overview" in str(m.value) for m in app.markdown)
    assert any("Cross-File Identities" in str(s.value) for s in app.subheader)
    assert any(metric.label == "Tokens in 2+ files" and metric.value == "1" for metric in app.metric)
    assert len(app.selectbox) == 1  # the file switcher is a radio, not a second selectbox
