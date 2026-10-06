import pytest

from privacygate.pipeline import process_document


def test_scaffold_cannot_process_or_approve_a_document(tmp_path):
    with pytest.raises(NotImplementedError, match="No privacy approval was issued"):
        process_document(tmp_path / "nonexistent.pdf")
    assert list(tmp_path.iterdir()) == []
