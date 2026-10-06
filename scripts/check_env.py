"""Check Phase 0 dependencies without initializing detectors or downloading models."""

import importlib
from importlib.metadata import version
import platform
import shutil
import subprocess
import sys

CORE_PACKAGES = {
    "streamlit": "streamlit",
    "pymupdf": "pymupdf",
    "python-docx": "docx",
    "python-pptx": "pptx",
    "presidio-analyzer": "presidio_analyzer",
    "presidio-anonymizer": "presidio_anonymizer",
    "spacy": "spacy",
    "pandas": "pandas",
    "pytesseract": "pytesseract",
    "pillow": "PIL",
}


def main() -> int:
    """Return nonzero for an invalid Python environment; OCR is optional in Phase 0."""
    print("PrivacyGate environment diagnostic", flush=True)
    python_ok = sys.version_info[:2] == (3, 11)
    print(f"[{'OK' if python_ok else 'ERROR'}] Python {platform.python_version()} (required: 3.11.x)")
    print(f"Interpreter: {sys.executable}", flush=True)
    environment_ok = python_ok

    for distribution, module in CORE_PACKAGES.items():
        try:
            importlib.import_module(module)
            installed_version = version(distribution)
        except Exception as exc:
            print(f"[ERROR] {distribution}: missing or cannot import ({type(exc).__name__})", flush=True)
            environment_ok = False
        else:
            print(f"[OK] {distribution} {installed_version} (Python package)", flush=True)

    print("[INFO] spaCy language models are separate; none are required or downloaded in Phase 0.")
    executable = shutil.which("tesseract")
    if executable is None:
        print("[WARNING] Tesseract executable not found on PATH. pytesseract alone does not provide OCR.")
        print("Install Tesseract separately and add it to PATH before Phase 1 OCR work.")
    else:
        try:
            result = subprocess.run(
                [executable, "--version"], capture_output=True, text=True,
                errors="replace", timeout=10, check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[WARNING] Tesseract executable found but could not run ({type(exc).__name__}): {executable}")
        else:
            output = (result.stdout or result.stderr).strip().splitlines()
            print(f"[OK] Tesseract executable: {executable} ({output[0] if output else 'version not reported'})")

    print("Phase 0 Python environment: " + ("OK" if environment_ok else "FAILED; run uv sync."))
    return 0 if environment_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
