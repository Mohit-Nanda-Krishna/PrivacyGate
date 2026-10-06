"""Diagnostic behavior must not depend on a system Tesseract installation."""

from pathlib import Path
import runpy
import subprocess
from unittest.mock import Mock

import pytest


@pytest.fixture
def diagnostic(monkeypatch):
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts/check_env.py"))
    main = namespace["main"]
    monkeypatch.setitem(main.__globals__, "importlib", Mock())
    monkeypatch.setitem(main.__globals__, "version", Mock(return_value="test-version"))
    monkeypatch.setitem(main.__globals__, "sys", Mock(version_info=(3, 11, 9), executable="python"))
    monkeypatch.setitem(main.__globals__, "shutil", Mock(which=Mock(return_value=None)))
    return main


def test_missing_tesseract_warns_but_python_environment_passes(diagnostic, capsys):
    assert diagnostic() == 0
    output = capsys.readouterr().out
    assert "[OK] pytesseract test-version (Python package)" in output
    assert "[OK] spacy test-version (Python package)" in output
    assert "[WARNING] Tesseract executable not found" in output


def test_missing_python_package_fails_diagnostic(diagnostic, capsys):
    diagnostic.__globals__["importlib"].import_module.side_effect = ImportError
    assert diagnostic() == 1
    assert "[ERROR] pytesseract: missing or cannot import" in capsys.readouterr().out


def test_wrong_python_version_fails_diagnostic(diagnostic, capsys):
    diagnostic.__globals__["sys"].version_info = (3, 12, 0)
    assert diagnostic() == 1
    assert "[ERROR] Python" in capsys.readouterr().out


@pytest.mark.parametrize("failure", [OSError(), subprocess.TimeoutExpired("tesseract", 10)])
def test_unusable_tesseract_warns_without_crashing(diagnostic, monkeypatch, capsys, failure):
    diagnostic.__globals__["shutil"].which.return_value = "tesseract"
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=failure))
    assert diagnostic() == 0
    assert "found but could not run" in capsys.readouterr().out


def test_available_tesseract_is_reported_separately(diagnostic, monkeypatch, capsys):
    diagnostic.__globals__["shutil"].which.return_value = "tesseract"
    runner = Mock(return_value=subprocess.CompletedProcess(
        ["tesseract", "--version"], 0, stdout="tesseract test-version\n", stderr="",
    ))
    monkeypatch.setattr(subprocess, "run", runner)
    assert diagnostic() == 0
    assert "[OK] Tesseract executable:" in capsys.readouterr().out
    assert runner.call_args.args[0] == ["tesseract", "--version"]
